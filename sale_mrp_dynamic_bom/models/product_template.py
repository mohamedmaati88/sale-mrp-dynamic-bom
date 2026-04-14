from odoo import _, api, fields, models
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
        string='Lock MO',
        default='on_mo_done',
        required=True,
        help=(
            'on_mo_done    → editing blocked only after the MO is closed (Done).\n'
            'on_mo_confirm → editing blocked once the MO is confirmed.\n'
            'manual        → a lock toggle on the MO form lets the production '
            'operator block updates at any time.'
        ),
    )
    pricing_mode = fields.Selection(
        selection=[
            ('components', 'Component Price'),
            ('product', 'Product Price'),
            ('components_cost', 'Components Cost'),
        ],
        string='Pricing',
        default='components',
        required=True,
        help=(
            'Component Price    → SO price = sum of component sale prices.\n'
            'Product Price      → SO price = product\'s own sale price (unchanged).\n'
            'Components Cost    → SO price = sum of component costs + margin.'
        ),
    )
    margin_type = fields.Selection(
        selection=[
            ('percentage', 'Percentage (%)'),
            ('fixed', 'Fixed Amount'),
        ],
        string='Margin Type',
        default='percentage',
        help=(
            'Percentage  → unit price = cost × (1 + margin / 100).\n'
            'Fixed Amount → unit price = cost + margin.'
        ),
    )
    default_margin = fields.Float(
        string='Default Margin',
        default=0.0,
        digits='Product Price',
        help='Default margin value auto-filled on each selectable component. '
             'Can be overridden per component.',
    )
    disable_component_price_update = fields.Boolean(
        compute='_compute_disable_component_price_update',
        store=True,
    )

    @api.depends('pricing_mode')
    def _compute_disable_component_price_update(self):
        for rec in self:
            rec.disable_component_price_update = (rec.pricing_mode == 'product')
    selectable_component_ids = fields.One2many(
        comodel_name='mrp.selectable.component',
        inverse_name='product_tmpl_id',
        string='Selectable Components',
    )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _get_pending_operations(self):
        """Return counts of pending SO lines, invoices and MOs for this product.

        Returns a dict: {
            'sale_lines': recordset of open SO lines,
            'invoices':   recordset of draft/open invoices,
            'mos':        recordset of active MOs,
        }
        """
        self.ensure_one()
        product_ids = self.product_variant_ids.ids

        sale_lines = self.env['sale.order.line'].search([
            ('product_id', 'in', product_ids),
            ('has_dynamic_components', '=', True),
            ('order_id.state', 'in', ['sale', 'done']),
        ])

        invoices = self.env['account.move'].search([
            ('invoice_line_ids.product_id', 'in', product_ids),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'draft'),
        ])

        mos = self.env['mrp.production'].search([
            ('product_id', 'in', product_ids),
            ('is_dynamic_bom', '=', True),
            ('state', 'not in', ['done', 'cancel']),
        ])

        return {'sale_lines': sale_lines, 'invoices': invoices, 'mos': mos}

    def _raise_if_pending_operations(self, action_label):
        """Raise UserError if any pending SO/invoice/MO exists for this product."""
        self.ensure_one()
        ops = self._get_pending_operations()
        parts = []
        if ops['sale_lines']:
            orders = ops['sale_lines'].mapped('order_id.name')
            parts.append('• Open sale orders: %s' % ', '.join(orders))
        if ops['invoices']:
            inv_names = [n or '(Draft)' for n in ops['invoices'].mapped('name')]
            parts.append('• Draft invoices: %s' % ', '.join(inv_names))
        if ops['mos']:
            parts.append('• Active manufacturing orders: %s'
                         % ', '.join(ops['mos'].mapped('name')))
        if parts:
            raise UserError(
                _('Cannot %s for product "%s" while there are pending operations:'
                  '\n\n%s\n\n'
                  'Please complete or cancel all pending sale orders, invoices, '
                  'and manufacturing orders first.')
                % (action_label, self.display_name, '\n'.join(parts))
            )

    # ── Constraints / write overrides ──────────────────────────────────────

    @api.onchange('default_margin')
    def _onchange_default_margin(self):
        """Propagate default_margin to all selectable components immediately in the form."""
        for rec in self:
            rec.selectable_component_ids.update({'margin': rec.default_margin})

    def write(self, vals):
        for rec in self:
            # ── Guard: pricing_mode toggle ───────────────────────────────
            if 'pricing_mode' in vals:
                if vals['pricing_mode'] != rec.pricing_mode:
                    rec._raise_if_pending_operations('change "Pricing"')
            # ── Guard: enable_dynamic_bom → False ───────────────────────
            if 'enable_dynamic_bom' in vals:
                new_val = vals['enable_dynamic_bom']
                if not new_val and rec.enable_dynamic_bom:
                    rec._raise_if_pending_operations(
                        'disable "Enable Dynamic BOM"'
                    )
        res = super().write(vals)
        # When default_margin is saved, push to all existing selectable components
        if 'default_margin' in vals:
            for rec in self:
                rec.selectable_component_ids.write({'margin': vals['default_margin']})
        return res

    @api.onchange('enable_dynamic_bom')
    def _onchange_enable_dynamic_bom(self):
        if not self.enable_dynamic_bom and self._origin.enable_dynamic_bom:
            return {
                'warning': {
                    'title': _('Dynamic BOM Disabled'),
                    'message': _(
                        'Disabling Dynamic BOM will prevent users from selecting '
                        'components on new Sale Order lines. Existing Sale Order '
                        'line component selections will not be affected.'
                    ),
                }
            }
