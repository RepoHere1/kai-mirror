const fs = require('fs');
const path = require('path');

const STATE_FILE = path.join(__dirname, 'state.json');

const freshState = {
  mode: 'dry',
  no_lanes_enabled: true,
  all_no: {
    dry: { starting_balance: 303, balance: 303, positions: [], closed_trades: [], total_pnl: 0, entries: 0 },
    live: { starting_balance: 250, balance: 250, positions: [], closed_trades: [], total_pnl: 0, entries: 0 }
  },
  runtime: { clip: 5, min_edge: 0.001, max_price: 0.90, min_price: 0.05, take_profit: 0.90, stop_loss: 0.25, kelly_cap: 0.4, min_hold_sec: 30, entry_cooldown_sec: 60, max_hold_sec: 300, max_exposure_pct: 0.3, maker_only: true },
  signal_weights: { arbitrage: 1, imbalance: 0.7, volume: 0.6, cross_expiry: 0.5, whale: 0.3, black_scholes: 0.15, order_flow: 0.65, vol_rp: 0.55, term_struct: 0.45, funding_carry: 0.5, settlement_alpha: 0.7 },
  signal_outcomes: [],
  lanes: {},
  dry: { positions: [], closed: [], balance: 0, starting_balance: 303, entries: 0, running: false },
  alerts: { enabled: false, telegram_url: '', discord_url: '', last_sent: null },
  logs: [],
  booted_at: new Date().toISOString(),
  settlement_db: [],
  fill_quality_db: [],
  webhooks: [],
  live: { positions: [], closed: [], balance: 0, starting_balance: 0, entries: 0, running: false }
};

fs.writeFileSync(STATE_FILE, JSON.stringify(freshState, null, 1));
console.log('State reset to $303 DRY balance, all trades cleared');
console.log('Fresh state written to:', STATE_FILE);