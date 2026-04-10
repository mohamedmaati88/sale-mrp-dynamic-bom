{
    'name': 'Sale MRP Dynamic BOM',
    'version': '18.0.1.1.0',
    'category': 'Manufacturing',
    'summary': 'Select raw material components per Sale Order line to drive MO creation',
    'description': """
Sale MRP Dynamic BOM
====================

Allows configuring raw material components per Sale Order line from a
pre-defined list of selectable components on the product.

Key features:
- Component groups with single / multiple selection modes
- Mandatory and optional components per group
- Wizard-based component selector on each SO line
- Automatic Manufacturing Order creation on SO confirmation or
  immediately after component configuration on a confirmed SO
- Sync warnings when component selections or prices change after MO creation
- Quantity sync between SO line and MO without recreating the order
- Edit locking based on MO state (configurable per product)
    """,
    'author': 'Infiniarc',
    'depends': [
        'sale_management',
        'mrp',
        'stock',
        'account',
        'uom',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mrp_component_group_data.xml',
        'views/mrp_component_group_views.xml',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'views/sale_order_line_component_views.xml',
        'views/mrp_production_views.xml',
        'wizard/sale_component_selector_views.xml',
        'views/menu_views.xml',
        'report/dynamic_components_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sale_mrp_dynamic_bom/static/src/js/sale_order_dynamic_bom.js',
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
