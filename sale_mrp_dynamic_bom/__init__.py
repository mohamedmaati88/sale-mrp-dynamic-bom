from . import models
from . import wizard


def pre_init_hook(env):
    """Link any pre-existing mrp.component.group records (code=RAW/COLOR/ACC/PKG)
    to their XML IDs so that Odoo UPDATE them instead of trying to CREATE them,
    preventing UniqueViolation on reinstall when ir.model.data entries are missing.
    """
    mapping = {
        'RAW':   'mrp_component_group_raw',
        'COLOR': 'mrp_component_group_color',
        'ACC':   'mrp_component_group_accessories',
        'PKG':   'mrp_component_group_packaging',
    }
    IMD = env['ir.model.data']
    for code, xml_name in mapping.items():
        group = env['mrp.component.group'].search([('code', '=', code)], limit=1)
        if not group:
            continue
        exists = IMD.search([
            ('module', '=', 'sale_mrp_dynamic_bom'),
            ('name',   '=', xml_name),
        ], limit=1)
        if not exists:
            IMD.create({
                'module':   'sale_mrp_dynamic_bom',
                'name':     xml_name,
                'model':    'mrp.component.group',
                'res_id':   group.id,
                'noupdate': False,
            })
