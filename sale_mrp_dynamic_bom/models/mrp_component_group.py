from odoo import fields, models
from odoo.exceptions import UserError


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
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Uncheck to archive this component group.',
    )

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', 'Component group code must be unique.'),
    ]

    def unlink(self):
        """Prevent deletion if any selectable components are linked to this group."""
        linked = self.env['mrp.selectable.component'].search(
            [('group_id', 'in', self.ids)], limit=1
        )
        if linked:
            raise UserError(
                'Cannot delete component group "%s".\n\n'
                'It is linked to one or more selectable components on a product. '
                'Remove or reassign those components first, or archive this group instead.'
                % (linked.group_id.name,)
            )
        return super().unlink()
