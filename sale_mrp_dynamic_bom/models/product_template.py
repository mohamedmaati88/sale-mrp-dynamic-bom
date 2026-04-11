from odoo import api, fields, models


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
