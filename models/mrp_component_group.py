from odoo import fields, models


class MrpComponentGroup(models.Model):
    _name = 'mrp.component.group'
    _description = 'MRP Component Group'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    selection_mode = fields.Selection(
        selection=[
            ('single', 'Single Selection'),
            ('multiple', 'Multiple Selection'),
        ],
        string='Selection Mode',
        default='multiple',
        required=True,
    )
    is_required = fields.Boolean(
        string='Required',
        help='At least one component must be selected from this group',
    )

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', 'Component group code must be unique.'),
    ]
