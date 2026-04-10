from odoo import models


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _prepare_mo_vals(self, product_id, product_qty, product_uom, location_id,
                         name, origin, company_id, values, bom):
        res = super()._prepare_mo_vals(
            product_id, product_qty, product_uom, location_id,
            name, origin, company_id, values, bom,
        )
        sale_line = values.get('sale_line_id')
        if sale_line and hasattr(sale_line, 'selected_component_ids'):
            if sale_line.selected_component_ids:
                res['is_dynamic_bom'] = True
                res['dynamic_sale_line_id'] = sale_line.id
        return res
