from odoo import fields, models


class MrpProductionDynamicComponent(models.Model):
    _name = 'mrp.production.dynamic.component'
    _description = 'MRP Production Dynamic Component'
    _order = 'sequence, group_id, component_product_id'

    production_id = fields.Many2one(
        comodel_name='mrp.production',
        string='Manufacturing Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    component_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Component Product',
        required=True,
    )
    group_id = fields.Many2one(
        comodel_name='mrp.component.group',
        string='Component Group',
    )
    qty = fields.Float(
        string='Quantity',
        required=True,
        digits='Product Unit of Measure',
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unit of Measure',
        required=True,
    )
    sale_line_component_id = fields.Many2one(
        comodel_name='sale.order.line.component',
        string='Sale Line Component',
        ondelete='set null',
    )
    sequence = fields.Integer(string='Sequence', default=10)
