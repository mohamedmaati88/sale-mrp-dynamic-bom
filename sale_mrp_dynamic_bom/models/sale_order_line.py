import logging
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    adjustment_invoice_ids = fields.Many2many(
        comodel_name='account.move',
        relation='sale_order_dynamic_adjustment_invoice_rel',
        column1='order_id',
        column2='invoice_id',
        string='Price Adjustment Documents',
        copy=False,
    )

    @api.depends('order_line.invoice_lines', 'adjustment_invoice_ids')
    def _get_invoiced(self):
        super()._get_invoiced()
        for order in self:
            if order.adjustment_invoice_ids:
                combined = order.invoice_ids | order.adjustment_invoice_ids
                order.invoice_ids = combined
                order.invoice_count = len(combined)

    price_adjustment_pending = fields.Boolean(
        compute='_compute_price_adjustment_pending',
        string='Price Adjustment Pending',
        store=True,
    )
    price_adjustment_pending_products = fields.Char(
        compute='_compute_price_adjustment_pending',
        string='Products Needing Adjustment',
        store=True,
    )

    @api.depends(
        'order_line.price_unit',
        'order_line.has_dynamic_components',
        'order_line.invoice_lines.move_id.state',
        'order_line.invoice_lines.price_subtotal',
        'adjustment_invoice_ids',
        'adjustment_invoice_ids.state',
        'adjustment_invoice_ids.invoice_line_ids.name',
    )
    def _compute_price_adjustment_pending(self):
        AML = self.env['account.move.line']
        for order in self:
            pending_products = []
            for line in order.order_line.filtered(
                lambda l: l.has_dynamic_components and l.selected_component_ids
            ):
                # Robust search: try M2M first, fallback to domain search
                posted_lines = line.invoice_lines.filtered(
                    lambda l: l.move_id.state == 'posted'
                    and l.move_id.move_type == 'out_invoice'
                    and l.display_type not in ('line_section', 'line_note')
                )
                if not posted_lines:
                    posted_lines = AML.search([
                        ('sale_line_ids', 'in', [line.id]),
                        ('move_id.state', '=', 'posted'),
                        ('move_id.move_type', '=', 'out_invoice'),
                        ('display_type', 'not in', ['line_section', 'line_note']),
                    ])
                if not posted_lines:
                    continue

                total_amount = sum(l.price_subtotal for l in posted_lines)
                total_qty = sum(l.quantity for l in posted_lines)
                if total_qty <= 0:
                    continue

                product_key = '(%s)' % line.product_id.display_name
                for adj_move in order.adjustment_invoice_ids.filtered(
                    lambda m: m.state == 'posted'
                ):
                    for adj_line in adj_move.invoice_line_ids.filtered(
                        lambda l: product_key in (l.name or '')
                        and l.display_type not in ('line_section', 'line_note')
                    ):
                        if adj_move.move_type == 'out_invoice':
                            total_amount += adj_line.price_subtotal
                        else:
                            total_amount -= adj_line.price_subtotal

                effective_price = total_amount / total_qty
                if abs(line.price_unit - effective_price) < 0.001:
                    continue

                has_draft = any(
                    m.state == 'draft' and any(
                        product_key in (l.name or '')
                        for l in m.invoice_line_ids.filtered(
                            lambda l: l.display_type not in ('line_section', 'line_note')
                        )
                    )
                    for m in order.adjustment_invoice_ids
                )
                if not has_draft:
                    pending_products.append(line.product_id.display_name)

            order.price_adjustment_pending = bool(pending_products)
            order.price_adjustment_pending_products = ', '.join(pending_products)

    dynamic_component_line_count = fields.Integer(
        string='Dynamic Component Count',
        compute='_compute_dynamic_component_line_count',
    )
    components_need_sync = fields.Boolean(
        string='Components Need Sync',
        default=False,
        copy=False,
        help='True when component selections were changed but the MO has not been updated yet.',
    )
    price_needs_sync = fields.Boolean(
        string='Price Needs Sync',
        default=False,
        copy=False,
        help='True when component selections were changed but the SO line price has not been updated yet.',
    )
    components_sync_product_names = fields.Char(
        string='Products Needing Component Sync',
        compute='_compute_sync_product_names',
    )
    price_sync_product_names = fields.Char(
        string='Products Needing Price Sync',
        compute='_compute_sync_product_names',
    )
    has_unconfigured_dynamic_lines = fields.Boolean(
        string='Has Unconfigured Dynamic Lines',
        compute='_compute_unconfigured_dynamic_lines',
    )
    unconfigured_product_names = fields.Char(
        string='Unconfigured Dynamic Products',
        compute='_compute_unconfigured_dynamic_lines',
    )

    @api.depends('state', 'order_line.has_dynamic_components', 'order_line.selected_component_ids')
    def _compute_unconfigured_dynamic_lines(self):
        for order in self:
            if order.state != 'sale':
                order.has_unconfigured_dynamic_lines = False
                order.unconfigured_product_names = ''
                continue
            unconfigured = order.order_line.filtered(
                lambda l: l.has_dynamic_components and not l.selected_component_ids
            )
            order.has_unconfigured_dynamic_lines = bool(unconfigured)
            order.unconfigured_product_names = ', '.join(
                unconfigured.mapped('product_id.display_name')
            ) if unconfigured else ''

    @api.depends('order_line.line_components_need_sync', 'order_line.line_price_needs_sync',
                 'order_line.product_id')
    def _compute_sync_product_names(self):
        for order in self:
            comp_lines = order.order_line.filtered(lambda l: l.line_components_need_sync)
            price_lines = order.order_line.filtered(lambda l: l.line_price_needs_sync)
            order.components_sync_product_names = ', '.join(
                comp_lines.mapped('product_id.display_name')
            ) if comp_lines else ''
            order.price_sync_product_names = ', '.join(
                price_lines.mapped('product_id.display_name')
            ) if price_lines else ''

    @api.depends('order_line.selected_component_ids')
    def _compute_dynamic_component_line_count(self):
        for order in self:
            order.dynamic_component_line_count = sum(
                len(line.selected_component_ids) for line in order.order_line
            )

    def action_view_dynamic_component_lines(self):
        self.ensure_one()
        list_view = self.env.ref(
            'sale_mrp_dynamic_bom.sale_order_line_component_list_view',
            raise_if_not_found=False,
        )
        form_view = self.env.ref(
            'sale_mrp_dynamic_bom.sale_order_line_component_form_view',
            raise_if_not_found=False,
        )
        dynamic_lines = self.order_line.filtered(lambda l: l.has_dynamic_components)
        dynamic_line_ids = dynamic_lines.ids
        allowed_product_ids = dynamic_lines.mapped(
            'product_id.product_tmpl_id.selectable_component_ids.component_product_id'
        ).ids
        # Determine lock point based on component_lock_mode
        lock_modes = [l.product_id.component_lock_mode for l in dynamic_lines]
        if 'on_mo_confirm' in lock_modes:
            mo_state_domain = ('state', 'not in', ['draft', 'cancel'])
        else:
            mo_state_domain = ('state', '=', 'done')
        confirmed_mo = self.env['mrp.production'].search([
            ('is_dynamic_bom', '=', True),
            mo_state_domain,
            '|',
            ('origin', '=', self.name),
            ('procurement_group_id', '=',
             self.procurement_group_id.id if self.procurement_group_id else -1),
        ], limit=1)
        ctx = {
            'default_sale_line_id': dynamic_line_ids[0] if dynamic_line_ids else False,
            'dynamic_line_ids': dynamic_line_ids,
            'allowed_product_ids': allowed_product_ids,
            'mo_is_confirmed': bool(confirmed_mo),
        }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Dynamic Component Selections',
            'res_model': 'sale.order.line.component',
            'view_mode': 'list,form',
            'views': [
                (list_view.id if list_view else False, 'list'),
                (form_view.id if form_view else False, 'form'),
            ],
            'domain': [('sale_line_id', 'in', self.order_line.ids)],
            'context': ctx,
        }

    def action_update_components_on_mo(self):
        """
        Update the dynamic BOM lines and MO raw moves to match the current
        selected_component_ids on each SO line.
        Only operates on MOs that are still in 'draft' state.
        Raises UserError if the related MO is already confirmed.
        """
        self.ensure_one()
        MrpProduction = self.env['mrp.production']

        domain = [
            ('is_dynamic_bom', '=', True),
            '|',
            ('origin', '=', self.name),
            ('procurement_group_id', '=',
             self.procurement_group_id.id if self.procurement_group_id else -1),
        ]
        productions = MrpProduction.search(domain)

        if not productions:
            raise UserError('No dynamic manufacturing order found for this sale order.')

        # Determine blocked states based on component_lock_mode
        lock_modes = [
            l.product_id.component_lock_mode
            for l in self.order_line.filtered(lambda l: l.has_dynamic_components)
        ]
        if 'on_mo_confirm' in lock_modes:
            blocked = productions.filtered(lambda p: p.state not in ('draft', 'cancel'))
            allowed_states = ['draft']
            block_msg = 'already confirmed'
        elif 'manual' in lock_modes:
            blocked = productions.filtered(lambda p: p.lock_component_updates)
            allowed_states = ['draft', 'confirmed', 'progress', 'to_close']
            block_msg = 'manually locked by the production operator'
        else:
            blocked = productions.filtered(lambda p: p.state == 'done')
            allowed_states = ['draft', 'confirmed', 'progress', 'to_close']
            block_msg = 'already closed (Done)'

        if blocked:
            raise UserError(
                'The following manufacturing order(s) are %s '
                'and cannot be updated:\n%s' % (block_msg, ', '.join(blocked.mapped('name')))
            )

        updated = []
        for production in productions.filtered(lambda p: p.state in allowed_states):
            matching = self.order_line.filtered(
                lambda l, p=production: l.product_id.id == p.product_id.id
                and l.selected_component_ids
            )
            if not matching:
                continue
            sale_line = matching[0]

            # ── Rebuild BOM lines ──────────────────────────────────────
            bom = production.bom_id
            if not bom:
                continue

            bom.sudo().bom_line_ids.unlink()
            bom.sudo().write({
                'product_qty': 1,
                'bom_line_ids': [(0, 0, {
                    'product_id': comp.component_product_id.id,
                    'product_qty': comp.qty,
                    'product_uom_id': comp.uom_id.id,
                }) for comp in sale_line.selected_component_ids],
            })

            # ── Rebuild raw moves from updated BOM ─────────────────────
            production.sudo().move_raw_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')
            ).unlink()
            move_vals = production.sudo()._get_moves_raw_values()
            if move_vals:
                self.env['stock.move'].sudo().create(move_vals)

            updated.append(production.name)
            production.message_post(
                body='🔄 <b>Dynamic BOM updated</b> from sale order <b>%s</b> '
                     'with %d component(s).' % (self.name, len(sale_line.selected_component_ids))
            )

        if not updated:
            raise UserError('No draft manufacturing orders were found to update.')

        # Clear the sync warning
        self.components_need_sync = False

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Components Updated',
                'message': 'Manufacturing order(s) updated: %s' % ', '.join(updated),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_update_all_lines(self):
        """
        Bulk update: for every dynamic SO line that has components configured,
        sync the MO components and recalculate the unit price in one shot.
        Accessible from the Action dropdown on the SO form.
        """
        self.ensure_one()
        dynamic_lines = self.order_line.filtered(
            lambda l: l.has_dynamic_components and l.selected_component_ids
        )
        if not dynamic_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Nothing to Update',
                    'message': 'No configured dynamic lines found on this order.',
                    'type': 'info',
                    'sticky': False,
                },
            }

        errors = []
        updated = []
        for line in dynamic_lines:
            try:
                line.action_update_components()
                updated.append(line.product_id.display_name)
            except UserError as e:
                errors.append('• %s: %s' % (line.product_id.display_name, str(e)))

        if errors and not updated:
            raise UserError(
                'Could not update any line:\n%s' % '\n'.join(errors)
            )

        msg = 'Updated: %s' % ', '.join(updated)
        if errors:
            msg += '\n\nSkipped (blocked):\n%s' % '\n'.join(errors)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Update Complete',
                'message': msg,
                'type': 'success' if not errors else 'warning',
                'sticky': bool(errors),
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_cancel(self):
        """Cancel linked dynamic MOs when the SO is cancelled.

        - draft / confirmed (no work started) → cancel automatically
        - progress / to_close / done          → skip, warn on SO + MO chatter

        Uses cursor-level guard to prevent double-execution when Odoo's
        internal call chain re-invokes this method in the same transaction.
        """
        cr = self.env.cr
        if not hasattr(cr, '_dynamic_bom_cancel_ids'):
            cr._dynamic_bom_cancel_ids = set()

        to_process = self.filtered(lambda o: o.id not in cr._dynamic_bom_cancel_ids)
        if not to_process:
            return super().action_cancel()

        cr._dynamic_bom_cancel_ids.update(to_process.ids)

        for order in to_process:
            dynamic_mos = self.env['mrp.production'].sudo().search([
                ('is_dynamic_bom', '=', True),
                ('state', 'not in', ['cancel']),
                '|',
                ('origin', '=', order.name),
                ('procurement_group_id', '=',
                 order.procurement_group_id.id if order.procurement_group_id else -1),
            ])
            if not dynamic_mos:
                continue

            cancellable = dynamic_mos.filtered(
                lambda p: p.state == 'draft'
            )
            skipped = dynamic_mos.filtered(
                lambda p: p.state in ('confirmed', 'progress', 'to_close', 'done')
            )

            if cancellable:
                cancellable.sudo().action_cancel()
                for mo in cancellable:
                    mo.message_post(
                        body='🚫 <b>Manufacturing Order cancelled</b> automatically '
                             'because Sale Order <b>%s</b> was cancelled by <b>%s</b>.'
                             % (order.name, self.env.user.name)
                    )

            if skipped:
                warning_body = (
                    '<b>⚠️ Sale Order Cancelled — the following Manufacturing Orders '
                    'could not be cancelled automatically (already confirmed or in progress). '
                    'Please review them manually:</b>'
                    '<ul>%s</ul>'
                ) % ''.join(
                    '<li><a href="/odoo/manufacturing/%d">%s</a> — %s</li>'
                    % (mo.id, mo.name, mo.state)
                    for mo in skipped
                )
                order.message_post(body=warning_body)
                cancelled_by = self.env.user.name
                for mo in skipped:
                    mo.sudo().write({
                        'source_sale_order_cancelled': True,
                        'source_sale_order_name': order.name,
                    })
                    mo.message_post(
                        body='⚠️ <b>تم إلغاء أمر البيع المصدر / Source Sale Order '
                             '<a href="/odoo/sales/%d">%s</a> was cancelled</b> '
                             'by <b>%s</b>. This Manufacturing Order could not be '
                             'cancelled automatically (current state: <b>%s</b>). '
                             'Please review manually.'
                             % (order.id, order.name, cancelled_by, mo.state)
                    )

        return super().action_cancel()

    def action_confirm(self):
        # 1. Validate before confirming
        for order in self:
            for line in order.order_line:
                line._check_dynamic_components_configured()

        # 2. Standard SO confirmation (creates MOs via procurement)
        result = super().action_confirm()

        # 3. Create dynamic BOMs and link to MOs
        self._setup_dynamic_bom_on_productions()

        return result

    def _setup_dynamic_bom_on_productions(self):
        """
        For each dynamic SO line that has an MO without a dynamic BOM yet:
          1. Create a new mrp.bom whose lines = selected components
          2. Link the BOM to the MO
          3. Rebuild raw moves from the new BOM
          4. Reset MO to draft so the user reviews it before confirming
        """
        MrpProduction = self.env['mrp.production']
        MrpBom = self.env['mrp.bom']

        # ── Safety: block incompatible component combinations ──────────────
        for order in self:
            order.order_line._validate_component_compatibility()

        for order in self:
            dynamic_lines = order.order_line.filtered(
                lambda l: l.selected_component_ids
            )
            if not dynamic_lines:
                continue

            domain = [
                ('state', 'in', ['draft', 'confirmed', 'progress']),
                '|',
                ('origin', '=', order.name),
                ('procurement_group_id', '=',
                 order.procurement_group_id.id
                 if order.procurement_group_id else -1),
            ]
            productions = MrpProduction.search(domain)

            _logger.info(
                'sale_mrp_dynamic_bom: SO %s — %d MO(s) found',
                order.name, len(productions),
            )

            for production in productions:
                # Skip if we already built a dynamic BOM for this MO.
                # The BOM we create carries code=order.name, making it a
                # reliable "already processed" marker that works even when
                # dynamic_sale_line_id is set at MO creation time.
                if (production.is_dynamic_bom
                        and production.bom_id
                        and production.bom_id.code == order.name):
                    continue

                # Match MO → SO line: prefer exact link, fall back to product
                if production.dynamic_sale_line_id:
                    matching = dynamic_lines.filtered(
                        lambda l, p=production: l.id == p.dynamic_sale_line_id.id
                    )
                else:
                    matching = dynamic_lines.filtered(
                        lambda l, p=production: l.product_id.id == p.product_id.id
                    )

                if not matching:
                    continue
                sale_line = matching[0]

                bom_line_vals = [(0, 0, {
                    'product_id': comp.component_product_id.id,
                    'product_qty': comp.qty,
                    'product_uom_id': comp.uom_id.id,
                }) for comp in sale_line.selected_component_ids]

                new_bom = MrpBom.sudo().create({
                    'product_tmpl_id': sale_line.product_id.product_tmpl_id.id,
                    'product_id': sale_line.product_id.id,
                    'product_qty': 1,
                    'product_uom_id': production.product_uom_id.id,
                    'type': 'normal',
                    'code': order.name,
                    'bom_line_ids': bom_line_vals,
                    'company_id': production.company_id.id,
                })

                _logger.info(
                    'sale_mrp_dynamic_bom: created BOM %s for MO %s with %d line(s)',
                    new_bom.id, production.name, len(bom_line_vals),
                )

                production.sudo().write({
                    'bom_id': new_bom.id,
                    'dynamic_sale_line_id': sale_line.id,
                    'is_dynamic_bom': True,
                })

                production.sudo().move_raw_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                ).unlink()

                move_vals = production.sudo()._get_moves_raw_values()
                if move_vals:
                    self.env['stock.move'].sudo().create(move_vals)

                if production.state != 'draft':
                    production.sudo().write({'state': 'draft'})

                production.message_post(
                    body=(
                        '🔧 <b>Dynamic BOM</b> created from '
                        '<b>%s</b> with <b>%d</b> component(s):<br/>%s'
                    ) % (
                        order.name,
                        len(bom_line_vals),
                        '<br/>'.join(
                            '• %s × %.2f %s' % (
                                c.component_product_id.display_name,
                                c.qty,
                                c.uom_id.name,
                            )
                            for c in sale_line.selected_component_ids
                        ),
                    )
                )


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    selected_component_ids = fields.One2many(
        comodel_name='sale.order.line.component',
        inverse_name='sale_line_id',
        string='Selected Components',
    )
    has_dynamic_components = fields.Boolean(
        string='Has Dynamic Components',
        compute='_compute_has_dynamic_components',
        store=True,
    )
    components_configured = fields.Boolean(
        string='Components Configured',
        compute='_compute_components_configured',
        store=True,
    )
    component_count = fields.Integer(
        string='Component Count',
        compute='_compute_component_count',
    )
    line_components_need_sync = fields.Boolean(
        string='Components Need Sync',
        default=False,
        copy=False,
    )
    line_price_needs_sync = fields.Boolean(
        string='Price Needs Sync',
        default=False,
        copy=False,
    )
    mo_creation_pending = fields.Boolean(
        string='MO Creation Pending',
        default=False,
        copy=False,
    )
    last_component_update = fields.Datetime(
        string='Last Component Update',
        copy=False,
        readonly=True,
    )

    @api.depends('product_id', 'product_id.enable_dynamic_bom')
    def _compute_has_dynamic_components(self):
        for line in self:
            line.has_dynamic_components = bool(
                line.product_id and line.product_id.enable_dynamic_bom
            )

    @api.depends('selected_component_ids')
    def _compute_components_configured(self):
        for line in self:
            line.components_configured = bool(line.selected_component_ids)

    @api.depends('selected_component_ids')
    def _compute_component_count(self):
        for line in self:
            line.component_count = len(line.selected_component_ids)

    def action_view_components(self):
        """Open the component list filtered to this SO line only."""
        self.ensure_one()
        list_view = self.env.ref(
            'sale_mrp_dynamic_bom.sale_order_line_component_list_view',
            raise_if_not_found=False,
        )
        form_view = self.env.ref(
            'sale_mrp_dynamic_bom.sale_order_line_component_form_view',
            raise_if_not_found=False,
        )
        allowed_product_ids = self.product_id.product_tmpl_id\
            .selectable_component_ids.mapped('component_product_id').ids

        lock_mode = self.product_id.component_lock_mode
        if lock_mode == 'on_mo_confirm':
            mo_state_domain = ('state', 'not in', ['draft', 'cancel'])
        elif lock_mode == 'manual':
            mo_state_domain = ('lock_component_updates', '=', True)
        else:
            mo_state_domain = ('state', '=', 'done')
        confirmed_mo = self.env['mrp.production'].search([
            ('is_dynamic_bom', '=', True),
            ('product_id', '=', self.product_id.id),
            mo_state_domain,
            '|',
            ('origin', '=', self.order_id.name),
            ('procurement_group_id', '=',
             self.order_id.procurement_group_id.id
             if self.order_id.procurement_group_id else -1),
        ], limit=1)
        ctx = {
            'default_sale_line_id': self.id,
            'allowed_product_ids': allowed_product_ids,
            'mo_is_confirmed': bool(confirmed_mo),
        }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Components — %s' % self.product_id.display_name,
            'res_model': 'sale.order.line.component',
            'view_mode': 'list,form',
            'views': [
                (list_view.id if list_view else False, 'list'),
                (form_view.id if form_view else False, 'form'),
            ],
            'domain': [('sale_line_id', '=', self.id)],
            'context': ctx,
        }

    def action_update_components(self):
        """Update the dynamic MO BOM and raw moves for this SO line only."""
        self.ensure_one()
        # ── Safety: block incompatible component combinations ──────────────
        self._validate_component_compatibility()
        order = self.order_id
        MrpProduction = self.env['mrp.production']

        matching = MrpProduction.search([
            ('is_dynamic_bom', '=', True),
            ('dynamic_sale_line_id', '=', self.id),
        ])
        if not matching:
            raise UserError(
                'No dynamic manufacturing order found for "%s".'
                % self.product_id.display_name
            )

        lock_mode = self.product_id.component_lock_mode
        if lock_mode == 'on_mo_confirm':
            blocked = matching.filtered(lambda p: p.state not in ('draft', 'cancel'))
            block_msg = 'already confirmed'
        elif lock_mode == 'manual':
            blocked = matching.filtered(lambda p: p.lock_component_updates)
            block_msg = 'manually locked by the production operator'
        else:
            blocked = matching.filtered(lambda p: p.state == 'done')
            block_msg = 'already closed (Done)'

        if blocked:
            raise UserError(
                'Manufacturing order "%s" is %s and cannot be updated.'
                % (blocked[0].name, block_msg)
            )

        production = matching[0]
        bom = production.bom_id
        if not bom:
            raise UserError('No BOM found for manufacturing order "%s".' % production.name)

        # Rebuild BOM lines
        bom.sudo().bom_line_ids.unlink()
        bom.sudo().write({
            'product_qty': 1,
            'bom_line_ids': [(0, 0, {
                'product_id': comp.component_product_id.id,
                'product_qty': comp.qty,
                'product_uom_id': comp.uom_id.id,
            }) for comp in self.selected_component_ids],
        })

        # Rebuild raw moves
        production.sudo().move_raw_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        ).unlink()
        move_vals = production.sudo()._get_moves_raw_values()
        if move_vals:
            self.env['stock.move'].sudo().create(move_vals)

        production.message_post(
            body='🔄 <b>Dynamic BOM updated</b> from sale order <b>%s</b> '
                 'with %d component(s).' % (order.name, len(self.selected_component_ids))
        )

        # ── Update unit price from component subtotals ────────────────
        if not self.product_id.disable_component_price_update:
            total = sum(c.subtotal for c in self.selected_component_ids)
            self.price_unit = total
            self._adjust_invoices_for_price_update(total)

        # ── Record last update timestamp ──────────────────────────────
        self.last_component_update = fields.Datetime.now()

        # ── Clear sync flags ──────────────────────────────────────────
        self.line_components_need_sync = False
        self.line_price_needs_sync = False
        if not order.order_line.filtered(
            lambda l: l.id != self.id and l.line_components_need_sync
        ):
            order.components_need_sync = False
        if not order.order_line.filtered(
            lambda l: l.id != self.id and l.line_price_needs_sync
        ):
            order.price_needs_sync = False

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Updated',
                'message': 'Manufacturing order and unit price updated for "%s".' % self.product_id.display_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def write(self, vals):
        # Capture qty changes on dynamic lines before writing
        qty_change_lines = {}
        if 'product_uom_qty' in vals:
            for line in self:
                if line.has_dynamic_components and line.selected_component_ids:
                    qty_change_lines[line.id] = vals['product_uom_qty']
        res = super().write(vals)
        # Sync MO quantity after write
        for line in self.filtered(lambda l: l.id in qty_change_lines):
            line._sync_dynamic_mo_quantity(qty_change_lines[line.id])
        return res

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """Skip procurement for dynamic lines in two cases:
        1. Line has no components configured yet → prevent MO creation until Configure is done
        2. Line already has an active dynamic MO → qty sync handled by _sync_dynamic_mo_quantity
        """
        lines_to_skip = self.env['sale.order.line']
        for line in self:
            if not line.has_dynamic_components:
                continue
            # Case 1: no components configured → skip to prevent MO creation
            if not line.selected_component_ids:
                lines_to_skip |= line
                continue
            # Case 2: existing dynamic MO for THIS specific line → skip to prevent duplicate
            existing_mo = self.env['mrp.production'].sudo().search([
                ('is_dynamic_bom', '=', True),
                ('dynamic_sale_line_id', '=', line.id),
                ('state', 'not in', ['done', 'cancel']),
            ], limit=1)
            if existing_mo:
                lines_to_skip |= line
        return super(SaleOrderLine, self - lines_to_skip)._action_launch_stock_rule(
            previous_product_uom_qty=previous_product_uom_qty
        )

    def _sync_dynamic_mo_quantity(self, new_qty):
        """Update the related dynamic MO quantity and raw moves to match new SO line qty."""
        order = self.order_id
        productions = self.env['mrp.production'].sudo().search([
            ('is_dynamic_bom', '=', True),
            ('state', 'not in', ['done', 'cancel']),
            '|',
            ('origin', '=', order.name),
            ('procurement_group_id', '=',
             order.procurement_group_id.id if order.procurement_group_id else -1),
        ])
        matching = productions.filtered(
            lambda p: p.product_id.id == self.product_id.id
        )
        if not matching:
            return

        # Update main MO qty
        main_mo = matching[0]
        old_qty = main_mo.product_qty or 1.0

        if old_qty == new_qty:
            return

        ratio = new_qty / old_qty

        # Cancel extra MOs safely
        extra = matching[1:]
        if extra:
            try:
                extra.sudo().action_cancel()
            except Exception:
                pass

        # Update MO product_qty directly in DB to bypass Odoo's internal
        # move deletion/recreation logic which causes the constraint error
        self.env.cr.execute(
            "UPDATE mrp_production SET product_qty = %s WHERE id = %s",
            [new_qty, main_mo.id]
        )

        # Scale raw move quantities directly in DB for the same reason
        move_ids = main_mo.move_raw_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        ).ids
        if move_ids:
            self.env.cr.execute(
                "UPDATE stock_move SET product_uom_qty = product_uom_qty * %s "
                "WHERE id = ANY(%s)",
                [ratio, move_ids]
            )

        # Update delivery order outgoing moves via ORM (no constraint blocks this)
        delivery_moves = self.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        )
        if delivery_moves:
            delivery_moves.write({'product_uom_qty': new_qty})

        # Invalidate ORM cache so subsequent reads see the updated values
        self.env.invalidate_all()

        main_mo.message_post(
            body='📦 <b>Quantity updated to %.2f</b> from Sale Order <b>%s</b>.'
                 % (new_qty, order.name)
        )

    def _check_mo_not_confirmed(self):
        """Raise if the related dynamic MO is locked based on component_lock_mode."""
        lock_mode = self.product_id.component_lock_mode

        if lock_mode == 'on_mo_confirm':
            state_domain = ('state', 'not in', ['draft', 'cancel'])
            err_msg = 'The manufacturing order "%s" is already confirmed. ' \
                      'You cannot make changes after confirmation.'
        elif lock_mode == 'manual':
            state_domain = ('lock_component_updates', '=', True)
            err_msg = 'The manufacturing order "%s" is manually locked by the ' \
                      'production operator. No updates are allowed.'
        else:
            state_domain = ('state', '=', 'done')
            err_msg = 'The manufacturing order "%s" is already closed (Done). ' \
                      'You cannot make changes after the MO is closed.'

        productions = self.env['mrp.production'].search([
            ('is_dynamic_bom', '=', True),
            ('dynamic_sale_line_id', '=', self.id),
            state_domain,
        ], limit=1)
        if productions:
            raise UserError(err_msg % productions.name)

    def action_open_component_selector(self):
        self.ensure_one()
        self._check_mo_not_confirmed()
        wizard = self.env['sale.component.selector'].create({
            'sale_line_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Select Components',
            'res_model': 'sale.component.selector',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _adjust_invoices_for_price_update(self, new_price):
        """After price_unit is updated on the SO line, adjust linked invoices.

        Draft invoices:
            Update price_unit directly on the invoice line (treated as recreated).

        Posted invoices:
            Compute old_unit_price = sum(price_subtotal) / sum(quantity) across
            all posted customer invoices for this line.
            If new_price < old → create draft Credit Note for the difference.
            If new_price > old → create draft Invoice for the difference.

        Only applies to dynamic BOM products.
        """
        if not self.has_dynamic_components:
            return

        AML = self.env['account.move.line']

        def _find_inv_lines(state, move_type):
            """Search invoice lines linked to this SO line.

            Tries the standard Many2many first; falls back to a direct
            domain search (covers manually-created invoices that may not
            populate the M2M relation).
            """
            lines = self.invoice_lines.filtered(
                lambda l: l.move_id.state == state
                and l.move_id.move_type == move_type
                and l.display_type == 'product'
            )
            if not lines:
                lines = AML.search([
                    ('sale_line_ids', 'in', [self.id]),
                    ('move_id.state', '=', state),
                    ('move_id.move_type', '=', move_type),
                    ('display_type', 'not in', ['line_section', 'line_note']),
                ])
            return lines

        # ── Draft invoices: update price_unit directly ─────────────────────
        draft_inv_lines = _find_inv_lines('draft', 'out_invoice')
        for inv_line in draft_inv_lines:
            inv_line.with_context(check_move_validity=False).write({
                'price_unit': new_price,
                'name': 'update components',
            })

        # ── Posted invoices: create adjustment document ────────────────────
        posted_inv_lines = _find_inv_lines('posted', 'out_invoice')

        if not posted_inv_lines:
            return

        order = self.order_id
        total_amount = sum(l.price_subtotal for l in posted_inv_lines)
        total_qty = sum(l.quantity for l in posted_inv_lines)
        if total_qty <= 0:
            return

        # Add confirmed adjustment invoices/credit notes to get effective old price
        product_key = '(%s)' % self.product_id.display_name
        for adj_move in order.adjustment_invoice_ids.filtered(lambda m: m.state == 'posted'):
            for adj_line in adj_move.invoice_line_ids.filtered(
                lambda l: product_key in (l.name or '') and l.display_type == 'product'
            ):
                if adj_move.move_type == 'out_invoice':
                    total_amount += adj_line.price_subtotal
                else:
                    total_amount -= adj_line.price_subtotal

        # Effective old unit price (accounts for discounts and prior adjustments)
        old_unit_price = total_amount / total_qty
        diff = new_price - old_unit_price

        # ── Remove existing draft adjustments for this product ────────────
        # (they will be replaced with a fresh one reflecting the latest diff)
        existing_drafts = order.adjustment_invoice_ids.filtered(
            lambda m: m.state == 'draft'
            and m.invoice_line_ids.filtered(
                lambda l: '(%s)' % self.product_id.display_name in (l.name or '')
            )
        )
        if existing_drafts:
            order.adjustment_invoice_ids = [(3, m.id) for m in existing_drafts]
            existing_drafts.sudo().unlink()

        if abs(diff) < 0.001:
            return

        move_type = 'out_refund' if diff < 0 else 'out_invoice'

        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', order.company_id.id),
        ], limit=1)
        if not journal:
            return

        new_move = self.env['account.move'].sudo().create({
            'move_type': move_type,
            'partner_id': order.partner_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_origin': order.name,
            'journal_id': journal.id,
            'invoice_line_ids': [(0, 0, {
                'account_id': (
                    self.product_id.property_account_income_id
                    or self.product_id.categ_id.property_account_income_categ_id
                ).id,
                'name': 'update components (%s)' % self.product_id.display_name,
                'quantity': total_qty,
                'price_unit': abs(diff),
                'product_uom_id': self.product_uom.id,
            })],
        })
        order.adjustment_invoice_ids = [(4, new_move.id)]

        # ── Capture diff snapshots on the adjustment document ─────────────────
        Snapshot = self.env['sale.invoice.component.snapshot'].sudo()
        current_comps = {
            c.component_product_id.id: c
            for c in self.selected_component_ids
        }
        update_dt = self.last_component_update

        # ── Build the accumulated billed state from ALL confirmed invoices ────
        # Step 1: normal snapshots from original posted invoices (chronological)
        prev_qty = {}   # {product_id: effective_billed_qty}
        prev_meta = {}  # {product_id: snapshot/component record for metadata}

        for prev_inv in posted_inv_lines.mapped('move_id').sorted(
            lambda m: m.invoice_date or m.date
        ):
            for snap in prev_inv.component_snapshot_ids.filtered(
                lambda s: s.sale_line_id.id == self.id and s.snapshot_type == 'normal'
            ):
                pid = snap.component_product_id.id
                prev_qty[pid] = snap.qty
                prev_meta[pid] = snap

        # Step 2: apply confirmed adjustment snapshots in chronological order
        # (additions increase the billed qty, reductions decrease it)
        for adj_inv in order.adjustment_invoice_ids.filtered(
            lambda m: m.state == 'posted'
        ).sorted(lambda m: m.invoice_date or m.date):
            for snap in adj_inv.component_snapshot_ids.filtered(
                lambda s: s.sale_line_id.id == self.id
            ):
                pid = snap.component_product_id.id
                if snap.snapshot_type == 'addition':
                    prev_qty[pid] = prev_qty.get(pid, 0) + snap.qty
                elif snap.snapshot_type == 'reduction':
                    prev_qty[pid] = max(prev_qty.get(pid, 0) - snap.qty, 0)
                    if prev_qty.get(pid, 0) <= 0:
                        prev_qty.pop(pid, None)
                prev_meta[pid] = snap  # keep most recent record for metadata

        def _create_diff_snap(source, qty_val, stype):
            """Write one snapshot row linked to the new adjustment move."""
            Snapshot.create({
                'invoice_id': new_move.id,
                'sale_line_id': self.id,
                'product_display_name': self.product_id.display_name,
                'component_product_id': source.component_product_id.id,
                'group_id': source.group_id.id if source.group_id else False,
                'qty': qty_val,
                'uom_id': source.uom_id.id if source.uom_id else False,
                'sale_price': source.sale_price,
                'subtotal': source.sale_price * qty_val,
                'notes': source.notes or '',
                'snapshot_type': stype,
                'sequence': getattr(source, 'sequence', 10),
                'update_date': update_dt,
            })

        # ── Compute both additions and reductions vs accumulated billed state ─
        if prev_qty:
            # Components added or with increased qty vs billed state
            for prod_id, comp in current_comps.items():
                prev_eff = prev_qty.get(prod_id, 0.0)
                if comp.qty > prev_eff + 0.001:
                    _create_diff_snap(comp, comp.qty - prev_eff, 'addition')

            # Components removed or with decreased qty vs billed state
            for prod_id, eff_qty in list(prev_qty.items()):
                curr = current_comps.get(prod_id)
                curr_qty = curr.qty if curr else 0.0
                if curr_qty < eff_qty - 0.001:
                    # Prefer current component for metadata (has live price/group);
                    # fall back to last known snapshot if component was removed
                    source = curr if curr else prev_meta.get(prod_id)
                    if source:
                        _create_diff_snap(source, eff_qty - curr_qty, 'reduction')
        else:
            # No prior snapshots (module installed after original invoice posting):
            # treat all current components as additions so the report shows something
            for comp in self.selected_component_ids:
                _create_diff_snap(comp, comp.qty, 'addition')

        doc_type = 'Credit Note' if move_type == 'out_refund' else 'Invoice'
        order.message_post(body=Markup(
            '📄 <b>%s created</b> (draft) — price adjustment for product <b>%s</b>: '
            '<a data-oe-model="account.move" data-oe-id="%d">View %s</a> — '
            'Amount: <b>%.2f</b> (%.2f per unit × %.2f units)'
        ) % (
            doc_type,
            self.product_id.display_name,
            new_move.id, doc_type,
            abs(diff) * total_qty, abs(diff), total_qty,
        ))

    def action_update_price_from_components(self):
        """Kept for backward compatibility — delegates to action_update_components."""
        return self.action_update_components()

    def _validate_component_compatibility(self):
        """Raise UserError if any two selected components on this line are
        incompatible.  Called before BOM creation / update as a safety net
        beyond the wizard validation.
        """
        for line in self.filtered(
            lambda l: l.has_dynamic_components and l.selected_component_ids
        ):
            sc_records = line.selected_component_ids.mapped(
                'selectable_component_id'
            ).filtered(bool)
            errors = []
            checked = set()
            for sc in sc_records:
                for incompat in sc.incompatible_component_ids:
                    if incompat in sc_records:
                        pair = frozenset([sc.id, incompat.id])
                        if pair not in checked:
                            checked.add(pair)
                            errors.append(
                                '• "%s"  ↔  "%s"'
                                % (
                                    sc.component_product_id.display_name,
                                    incompat.component_product_id.display_name,
                                )
                            )
            if errors:
                raise UserError(
                    'Product "%s": the following selected components are '
                    'incompatible and cannot be used together:\n\n%s'
                    % (line.product_id.display_name, '\n'.join(errors))
                )

    def _check_dynamic_components_configured(self):
        for line in self:
            if not line.has_dynamic_components or line.product_uom_qty <= 0:
                continue
            if not line.selected_component_ids:
                raise UserError(
                    'Please configure components for product "%s" before '
                    'confirming the order (click the Configure button).'
                    % line.product_id.display_name
                )

