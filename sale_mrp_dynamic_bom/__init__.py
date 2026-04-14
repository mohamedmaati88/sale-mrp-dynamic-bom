from . import models
from . import wizard


def pre_init_hook(env):
    """Link any pre-existing mrp.component.group records (code=RAW/COLOR/ACC/PKG)
    to their XML IDs so that Odoo UPDATEs them instead of trying to CREATE them,
    preventing UniqueViolation on reinstall when ir.model.data entries are missing.

    Uses raw SQL because pre_init_hook runs before the module models are loaded
    into the registry — ORM access to mrp.component.group is not available yet.
    """
    cr = env.cr

    # Safety: do nothing if the table doesn't exist yet (fresh install)
    cr.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'mrp_component_group'
        )
    """)
    if not cr.fetchone()[0]:
        return

    mapping = {
        'RAW':   'mrp_component_group_raw',
        'COLOR': 'mrp_component_group_color',
        'ACC':   'mrp_component_group_accessories',
        'PKG':   'mrp_component_group_packaging',
    }

    for code, xml_name in mapping.items():
        # Find existing record by code
        cr.execute(
            "SELECT id FROM mrp_component_group WHERE code = %s LIMIT 1",
            (code,),
        )
        row = cr.fetchone()
        if not row:
            continue
        group_id = row[0]

        # Skip if ir.model.data entry already exists
        cr.execute("""
            SELECT 1 FROM ir_model_data
            WHERE module = 'sale_mrp_dynamic_bom' AND name = %s
            LIMIT 1
        """, (xml_name,))
        if cr.fetchone():
            continue

        # Create the linking ir.model.data entry
        cr.execute("""
            INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
            VALUES ('sale_mrp_dynamic_bom', %s, 'mrp.component.group', %s, false)
        """, (xml_name, group_id))
