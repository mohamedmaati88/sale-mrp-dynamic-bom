from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    is_dynamic_bom = fields.Boolean(
        string='Is Dynamic BOM',
        default=False,
        copy=False,
    )
    dynamic_component_ids = fields.One2many(
        comodel_name='mrp.production.dynamic.component',
        inverse_name='production_id',
        string='Dynamic Components',
    )
    dynamic_sale_line_id = fields.Many2one(
        comodel_name='sale.order.line',
        string='Source Sale Line',
        copy=False,
        index=True,
    )
    so_components_need_sync = fields.Boolean(
        string='Components Need Sync',
        compute='_compute_so_sync_flags',
    )
    so_price_needs_sync = fields.Boolean(
        string='Price Needs Sync',
        compute='_compute_so_sync_flags',
    )
    lock_component_updates = fields.Boolean(
        string='Lock Component Updates',
        default=False,
        copy=False,
        help='When enabled, no component updates from the Sale Order are allowed '
             'for this manufacturing order. Only applies when the product uses '
             '"Manual Lock by Operator" mode.',
    )
    source_so_cancelled = fields.Boolean(
        string='Source Sale Order Cancelled',
        default=False,
        copy=False,
        help='Set to True when the originating Sale Order is cancelled while '
             'this MO is still confirmed.',
    )
    show_manual_lock = fields.Boolean(
        string='Show Manual Lock',
        compute='_compute_show_manual_lock',
    )

    @api.depends('is_dynamic_bom', 'dynamic_sale_line_id',
                 'dynamic_sale_line_id.product_id.component_lock_mode')
    def _compute_show_manual_lock(self):
        for production in self:
            if not production.is_dynamic_bom or not production.dynamic_sale_line_id:
                production.show_manual_lock = False
                continue
            lock_mode = production.dynamic_sale_line_id.product_id.component_lock_mode
            production.show_manual_lock = (lock_mode == 'manual')

    @api.depends('is_dynamic_bom', 'dynamic_sale_line_id',
                 'dynamic_sale_line_id.line_components_need_sync',
                 'dynamic_sale_line_id.line_price_needs_sync')
    def _compute_so_sync_flags(self):
        for production in self:
            if not production.is_dynamic_bom:
                production.so_components_need_sync = False
                production.so_price_needs_sync = False
                continue
            sale_line = production.dynamic_sale_line_id
            production.so_components_need_sync = (
                sale_line.line_components_need_sync if sale_line else False
            )
            production.so_price_needs_sync = (
                sale_line.line_price_needs_sync if sale_line else False
            )

    def button_mark_done(self):
        self._check_dynamic_sync_before_confirm()
        return super().button_mark_done()

    def action_confirm(self):
        for production in self.filtered(lambda p: p.is_dynamic_bom):
            lock_mode = production.dynamic_sale_line_id.product_id.component_lock_mode \
                if production.dynamic_sale_line_id else 'on_mo_done'
            if lock_mode == 'on_mo_confirm':
                production._check_dynamic_sync_before_confirm()
        return super().action_confirm()

    def _check_dynamic_sync_before_confirm(self):
        for production in self.filtered(lambda p: p.is_dynamic_bom):
            sale_line = production.dynamic_sale_line_id
            if not sale_line:
                continue
            messages = []
            if sale_line.line_components_need_sync:
                messages.append(
                    _('• Component selections have changed. Please click '
                      '"Update Components" on sale order line "%s" first.')
                    % sale_line.product_id.display_name
                )
            if sale_line.line_price_needs_sync:
                messages.append(
                    _('• Unit price has changed. Please click '
                      '"Update Price" on sale order line "%s" first.')
                    % sale_line.product_id.display_name
                )
            if messages:
                raise UserError(
                    _('Cannot confirm manufacturing order "%s".\n\n%s')
                    % (production.name, '\n'.join(messages))
                )
