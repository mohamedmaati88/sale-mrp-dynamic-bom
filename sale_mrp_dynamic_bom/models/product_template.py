from odoo import api, fields, models
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    enable_dynamic_bom = fields.Boolean(
        string='Enable Dynamic BOM',
        default=False,
        help='Allow users to select components per Sale Order',
    )
    component_lock_mode = fields.Selection(
        selection=[
            ('on_mo_done', 'Lock After MO Done'),
            ('on_mo_confirm', 'Lock After MO Confirm'),
            ('manual', 'Manual Lock by Operator'),
        ],
        string='Lock After MO Confirm',
        default='on_mo_done',
        required=True,
        help=(
            'on_mo_done    → editing blocked only after the MO is closed (Done).\n'
            'on_mo_confirm → editing blocked once the MO is confirmed.\n'
            'manual        → a lock toggle on the MO form lets the production '
            'operator block updates at any time.'
        ),
    )
    disable_component_price_update = fields.Boolean(
        string='Disable Price Update from Components',
        default=False,
        help='If enabled, updating components on a Sale Order line will NOT '
             'recalculate the unit sale price from component subtotals. '
             'The product\'s normal sale price will be kept unchanged.',
    )
    selectable_component_ids = fields.One2many(
        comodel_name='mrp.selectable.component',
        inverse_name='product_tmpl_id',
        string='Selectable Components',
    )

    @api.onchange('enable_dynamic_bom')
    def _onchange_enable_dynamic_bom(self):
        if not self.enable_dynamic_bom and self._origin.enable_dynamic_bom:
            return {
                'warning': {
                    'title': 'Dynamic BOM Disabled',
                    'message': (
                        'Disabling Dynamic BOM will prevent users from selecting '
                        'components on new Sale Order lines. Existing Sale Order '
                        'line component selections will not be affected.'
                    ),
                }
            }

    def write(self, vals):
        # ── Guard: block disabling enable_dynamic_bom if pending operations exist ──
        if 'enable_dynamic_bom' in vals and not vals['enable_dynamic_bom']:
            for tmpl in self.filtered(lambda t: t.enable_dynamic_bom):
                pending = tmpl._get_pending_operations_summary()
                if pending:
                    raise UserError(
                        'Cannot disable Dynamic BOM for "%s".\n\n'
                        'Please complete or cancel all pending operations first:\n\n%s'
                        % (tmpl.name, pending)
                    )

        # ── Guard: block changing disable_component_price_update if pending operations exist ──
        if 'disable_component_price_update' in vals:
            for tmpl in self:
                if tmpl.disable_component_price_update != vals['disable_component_price_update']:
                    pending = tmpl._get_pending_operations_summary()
                    if pending:
                        raise UserError(
                            'Cannot change "Disable Price Update from Components" for "%s".\n\n'
                            'Please complete or cancel all pending operations first:\n\n%s'
                            % (tmpl.name, pending)
                        )

        return super().write(vals)

    def _get_pending_operations_summary(self):
        """Return a formatted string listing pending SOs, MOs, and invoices for this
        product template, or an empty string if none exist."""
        product_ids = self.product_variant_ids.ids
        if not product_ids:
            return ''

        messages = []

        # Pending Sale Orders (not done / not cancelled)
        so_lines = self.env['sale.order.line'].sudo().search([
            ('product_id', 'in', product_ids),
            ('order_id.state', 'in', ('draft', 'sent', 'sale')),
        ], limit=10)
        if so_lines:
            so_names = ', '.join(dict.fromkeys(so_lines.mapped('order_id.name')))
            messages.append('• أوامر البيع / Sale Orders: %s' % so_names)

        # Pending Manufacturing Orders
        pending_mos = self.env['mrp.production'].sudo().search([
            ('product_id', 'in', product_ids),
            ('state', 'not in', ('done', 'cancel')),
        ], limit=10)
        if pending_mos:
            mo_names = ', '.join(pending_mos.mapped('name'))
            messages.append('• أوامر التصنيع / Manufacturing Orders: %s' % mo_names)

        # Pending Invoices (draft or posted, not cancelled)
        pending_invs = self.env['account.move'].sudo().search([
            ('invoice_line_ids.product_id', 'in', product_ids),
            ('state', 'in', ('draft', 'posted')),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
        ], limit=10)
        if pending_invs:
            inv_names = ', '.join(pending_invs.mapped('name'))
            messages.append('• الفواتير / Invoices: %s' % inv_names)

        return '\n'.join(messages)
