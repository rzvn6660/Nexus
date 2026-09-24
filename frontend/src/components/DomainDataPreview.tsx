import React from 'react';
import { ShoppingCart, Users, Package, Boxes, Receipt, Clock } from 'lucide-react';

const DOMAIN_ENTITIES = [
  {
    name: 'Sales & Transactions',
    scope: 'Initial Scope',
    status: 'Ready for Schema',
    icon: <ShoppingCart className="w-4 h-4 text-emerald-400" />,
    description: 'Transaction timestamps, line items, gross amount, discounts applied, net total, payment methods.',
  },
  {
    name: 'Customers & Segments',
    scope: 'Initial Scope',
    status: 'Ready for Schema',
    icon: <Users className="w-4 h-4 text-cyan-400" />,
    description: 'Customer profiles, acquisition channel, order history, frequency, churn risk indicators.',
  },
  {
    name: 'Product Catalog',
    scope: 'Initial Scope',
    status: 'Ready for Schema',
    icon: <Package className="w-4 h-4 text-blue-400" />,
    description: 'SKU, product name, category, unit cost (COGS), selling price, unit of measure, status.',
  },
  {
    name: 'Inventory Levels',
    scope: 'Initial Scope',
    status: 'Ready for Schema',
    icon: <Boxes className="w-4 h-4 text-amber-400" />,
    description: 'Current stock on hand, reorder thresholds, warehouse location, stockout history.',
  },
  {
    name: 'Operating Expenses',
    scope: 'Initial Scope',
    status: 'Ready for Schema',
    icon: <Receipt className="w-4 h-4 text-rose-400" />,
    description: 'Rent, logistics, utilities, payroll, and marketing spend for complete net profit modeling.',
  },
  {
    name: 'Suppliers & Branches',
    scope: 'Later Phase',
    status: 'Planned',
    icon: <Clock className="w-4 h-4 text-purple-400" />,
    description: 'Vendor lead times, multi-branch inventory transfers, promotional campaigns, and tiered pricing.',
  },
];

export const DomainDataPreview: React.FC = () => {
  return (
    <div className="glass-panel rounded-2xl p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-6 gap-2">
        <div>
          <h3 className="text-base font-semibold text-white">Target Initial Business Domain</h3>
          <p className="text-xs text-slate-400">
            Focused on small retail / distribution operations — depth over superficial breadth
          </p>
        </div>
        <span className="text-[11px] font-mono px-2.5 py-1 rounded-full bg-slate-800 text-cyan-300 border border-slate-700 self-start sm:self-auto">
          Retail & Distribution Model
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
        {DOMAIN_ENTITIES.map((entity) => (
          <div
            key={entity.name}
            className="p-3.5 rounded-xl bg-slate-900/50 border border-slate-800 hover:border-slate-700 transition-colors"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="p-1.5 rounded-lg bg-slate-800/80 border border-slate-700">
                  {entity.icon}
                </span>
                <span className="text-xs font-bold text-slate-200">{entity.name}</span>
              </div>
              <span
                className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${
                  entity.status === 'Ready for Schema'
                    ? 'bg-cyan-950/60 text-cyan-400 border border-cyan-800/60'
                    : 'bg-slate-800 text-slate-400'
                }`}
              >
                {entity.status}
              </span>
            </div>
            <p className="text-[11px] text-slate-300 leading-relaxed">{entity.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
};
