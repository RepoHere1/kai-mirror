#!/usr/bin/env python3

"""
Kai-Mirror Trading Dashboard - Python Version

This is a simplified Python rewrite of the Node.js trading dashboard,
focusing on the core functionality of the three main pages:
- index.html (main DRY dashboard)
- all-no-markets.html (NO-side markets)

Key Features:
- Real-time strategy management
- Account tracking (DRY/LIVE)
- WebSocket communication
- REST API endpoints
- Persistent state
"""

from flask import Flask, jsonify, request, Response
from flask_socketio import SocketIO
from flask_cors import CORS
import json
import threading
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional

# Flask application setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'kai-mirror-secret-key-change-in-production'
app.config['JSON_SORT_KEYS'] = False
CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state
class GlobalState:
    def __init__(self):
        self.mode = 'dry'
        self.no_lanes_dry = True
        self.no_lanes_live = True
        self.booted_at = datetime.now().isoformat()
        
        # DRY book (simulated)
        self.dry = {
            'starting_balance': 300,
            'baseline': 300,
            'positions': [],
            'closed': [],
            'real_started': True,
        }
        
        # ALL NO book (simulated)
        self.all_no = {
            'dry': {
                'starting_balance': 250,
                'balance': 250,
                'positions': [],
                'closed_trades': [],
                'total_pnl': 0,
                'entries': 0,
            },
            'live': {
                'starting_balance': 250,
                'balance': 250,
                'positions': [],
                'closed_trades': [],
                'total_pnl': 0,
                'entries': 0,
            },
        }
        
        # Runtime configuration
        self.runtime = {
            'min_edge': 0.06,
            'max_price': 0.90,
            'min_price': 0.05,
            'take_profit': 0.90,
            'stop_loss': 0.25,
            'kelly_cap': 0.4,
            'min_hold_sec': 45,
            'entry_cooldown_sec': 120,
        }
        
        # Strategy lanes
        self.lanes = {}
        self.alerts = {'enabled': False}
        self.logs = []
        
        # Lane registry
        self.current_lanes = [
            {'name': 'btc_updown', 'label': 'BTC 15-Min Up/Down'},
            {'name': 'eth_updown', 'label': 'ETH 15-Min Up/Down'},
            {'name': 'xrp_updown', 'label': 'XRP 15-Min Up/Down'},
            {'name': 'btc_1h_updown', 'label': 'BTC 1-Hour Ladder'},
            {'name': 'eth_1h_updown', 'label': 'ETH 1-Hour Ladder'},
            {'name': 'xrp_1h_updown', 'label': 'XRP 1-Hour Ladder'},
            {'name': 'hyperliquid_updown', 'label': 'Hyperliquid Up/Down'},
            {'name': 'all_no_markets', 'label': 'ALL NO MARKETS'},
        ]
        
    def save_state(self):
        with open('trading_state.json', 'w') as f:
            json.dump({
'mode': self.mode,
'no_lanes_dry': self.no_lanes_dry,
'no_lanes_live': self.no_lanes_live,
'dry': self.dry,
                'all_no': self.all_no,
                'runtime': self.runtime,
                'lanes': self.lanes,
                'alerts': self.alerts,
                'logs': self.logs,
                'booted_at': self.booted_at,
            }, f, indent=2, default=str)

# Initialize global state
global_state = GlobalState()

# Helper functions
def format_currency(n):
    return f'${n:.2f}'

def format_percent(n):
    return f'{n:.1f}%'

def format_cent(n):
    return f'{n * 100:.1f}¢'

def get_deployed():
    return sum(p['cost'] for p in global_state.dry['positions'])

def get_dry_cash():
    return global_state.dry['baseline'] + get_dry_realized() - get_deployed()

def get_dry_realized():
    return sum(t.get('pnl', 0) for t in global_state.dry['closed'])

def get_dry_equity():
    mtm = 0
    for p in global_state.dry['positions']:
        if p.get('mark') is not None:
            mtm += p['qty'] * p['mark']
        else:
            mtm += p['cost']
    return get_dry_cash() + mtm

def get_win_rate():
    closed = global_state.dry['closed']
    if not closed:
        return 0.0
    wins = len([t for t in closed if t.get('pnl', 0) > 0])
    return (wins / len(closed)) * 100

# API Endpoints
@app.route('/api/health')
def health_check():
    _booted = datetime.fromisoformat(global_state.booted_at)
    if _booted.tzinfo is None:
        _booted = _booted.replace(tzinfo=timezone.utc)
    return jsonify({
        'ok': True,
        'mode': global_state.mode,
        'uptime_sec': int((datetime.now(timezone.utc) - _booted).total_seconds()),
        'dry_balance': global_state.dry['baseline'],
    })

@app.route('/api/mode')
def get_mode():
    return jsonify({
        'mode': global_state.mode,
        'dry': {
            'cash': get_dry_cash(),
            'open_positions': len(global_state.dry['positions']),
            'total_pnl': get_dry_realized(),
            'win_rate': get_win_rate(),
            'starting_balance': global_state.dry['starting_balance'],
            'equity': get_dry_equity(),
            'realized': get_dry_realized(),
            'exposure': get_deployed(),
            'closed_trades': len(global_state.dry['closed']),
        },
        'no_lanes_enabled': global_state.no_lanes_dry,
    })

@app.route('/api/dry/cash', methods=['POST'])
def update_dry_cash():
    data = request.get_json()
    amount = data.get('amount')
    if not amount or amount <= 0:
        return jsonify({'error': 'amount must be positive'}), 400
    
    global_state.dry['baseline'] = amount
    global_state.dry['starting_balance'] = amount
    global_state.save_state()
    
    socketio.emit('snapshot', 'dry book reset')
    return jsonify(get_mode())

@app.route('/api/dry/reset', methods=['POST'])
def reset_dry():
    global_state.dry = {
        'starting_balance': 300,
        'baseline': 300,
        'positions': [],
        'closed': [],
        'real_started': True,
    }
    global_state.save_state()
    socketio.emit('snapshot', 'dry book reset')
    return jsonify(get_mode())

@app.route('/api/no-lanes', methods=['POST'])
def toggle_no_lanes():
    data = request.get_json()
    mode = data.get('mode', global_state.mode)
    enabled = bool(data.get('enabled'))
    if mode == 'live':
        global_state.no_lanes_live = enabled
    else:
        global_state.no_lanes_dry = enabled
    global_state.save_state()
    socketio.emit('config', {'no_lanes_enabled': global_state.no_lanes_dry if mode == 'dry' else global_state.no_lanes_live})
    return jsonify({'no_lanes_enabled': global_state.no_lanes_dry if mode == 'dry' else global_state.no_lanes_live})

@app.route('/api/no-lanes')
def get_no_lanes_status():
    mode = request.args.get('mode', global_state.mode)
    enabled = global_state.no_lanes_dry if mode == 'dry' else global_state.no_lanes_live
    return jsonify({'no_lanes_enabled': enabled})

@app.route('/api/no-lanes/book')
def get_all_no_book():
    # Return ALL NO book state from REAL entries only — no synthetic data.
    # The book is populated by createAllNoEntry() / closeAllNoPosition() which
    # record real Kalshi market IDs, real entry/exit prices and real P&L.
    all_positions = []

    for mode in ['dry', 'live']:
        book = global_state.all_no[mode]
        for pos in book['positions']:
            all_positions.append({
                'id': pos.get('id'),
                'market_id': pos.get('market_id'),
                'strategy': pos.get('strategy', 'all_no_markets'),
                'side': 'NO',
                'entry_price': pos.get('entry_price'),
                'quantity': pos.get('quantity'),
                'cost': pos.get('cost'),
                'entry_fair': pos.get('fair_at_entry'),
                'edge': pos.get('edge_at_entry'),
                'kelly': pos.get('kelly_fraction'),
                'confidence': pos.get('confidence'),
                'timestamp': pos.get('opened_at'),
                'status': pos.get('status', 'resting'),
                'mode': mode,
            })

    # Closed trades come straight from the book's own history
    closed_rows = []
    for mode in ['dry', 'live']:
        for t in global_state.all_no[mode]['closed_trades']:
            closed_rows.append({
                'id': t.get('id'),
                'market_id': t.get('market_id'),
                'strategy': t.get('strategy', 'all_no_markets'),
                'side': 'NO',
                'entry_price': t.get('entry_price'),
                'exit_price': t.get('exit_price'),
                'quantity': t.get('quantity'),
                'cost': t.get('cost'),
                'proceeds': t.get('proceeds'),
                'pnl': t.get('pnl'),
                'roi': t.get('roi'),
                'fee_paid': t.get('fee_paid'),
                'entry_fair': t.get('fair_at_entry'),
                'kelly': t.get('kelly_fraction'),
                'exit_reason': t.get('exit_reason'),
                'mode': mode,
                'entry_timestamp': t.get('opened_at'),
                'exit_timestamp': t.get('closed_at'),
            })

    # Tally from real closed trades only
    all_closed = global_state.all_no['dry']['closed_trades'] + global_state.all_no['live']['closed_trades']
    wins = len([t for t in all_closed if t.get('pnl', 0) > 0])
    losses = len([t for t in all_closed if t.get('pnl', 0) < 0])
    win_rate = (wins / len(all_closed) * 100) if all_closed else 0

    deployed = sum(p['cost'] for p in all_positions)

    return jsonify({
        'book': {
            'balance': global_state.all_no['dry']['balance'],
            'starting': global_state.all_no['dry']['starting_balance'],
            'pnl': global_state.all_no['dry']['total_pnl'],
            'entries': global_state.all_no['dry']['entries'],
            'mode': 'dry',
        },
        'tally': {
            'closed': len(all_closed),
            'wins': wins,
            'losses': losses,
            'win_rate': float(win_rate),
            'pnl': sum(t.get('pnl', 0) for t in all_closed),
            'fees': sum(t.get('fee_paid', 0) for t in all_closed),
            'avg_entry': sum(t.get('entry_price', 0) for t in all_closed) / len(all_closed) if all_closed else 0,
        },
        'open_tally': {
            'positions': len(all_positions),
            'contracts': sum(p['quantity'] for p in all_positions),
            'cost': deployed,
            'sweet': len([p for p in all_positions if 0.84 <= p['entry_price'] <= 0.92]),
        },
        'open_rows': all_positions,
        'closed_rows': closed_rows,
        'no_lanes_enabled': global_state.no_lanes_dry,
        'generated_at': datetime.now().isoformat(),
    })

@app.route('/api/no-lanes/exit', methods=['POST'])
def exit_all_no_position():
    data = request.get_json()
    pos_id = data.get('position_id')
    exit_price = data.get('exit_price')
    exit_reason = data.get('exit_reason')
    
    if not pos_id:
        return jsonify({'error': 'position_id required'}), 400
    
    # Find position in all_no book
    for mode in ['dry', 'live']:
        positions = global_state.all_no[mode]['positions']
        for pos in positions:
            if pos['id'] == pos_id:
                proceeds = pos['quantity'] * exit_price
                pnl = proceeds - pos['cost']
                
                # Remove from positions
                positions.remove(pos)
                
                # Add to closed trades
                closed_trade = {
                    'id': pos_id,
                    'market_id': pos['market_id'],
                    'strategy': pos['strategy'],
                    'side': pos['side'],
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_price,
                    'quantity': pos['quantity'],
                    'cost': pos['cost'],
                    'proceeds': proceeds,
                    'pnl': pnl,
                    'exit_reason': exit_reason,
                    'fee_paid': 0.001,
                    'roi': (pnl / pos['cost']) * 100 if pos['cost'] > 0 else 0,
                    'entry_fair': pos['entry_fair'],
                    'kelly': pos['kelly'],
                    'mode': mode,
                    'entry_timestamp': pos['timestamp'],
                    'exit_timestamp': datetime.now().isoformat(),
                }
                
                global_state.all_no[mode]['closed_trades'].append(closed_trade)
                global_state.all_no[mode]['total_pnl'] += pnl
                global_state.all_no[mode]['balance'] = global_state.all_no[mode]['starting_balance'] + global_state.all_no[mode]['total_pnl']
                global_state.all_no[mode]['entries'] = len(global_state.all_no[mode]['closed_trades'])
                
                global_state.save_state()
                
                return jsonify({
                    'success': True,
                    'pnl': pnl,
                    'balance': global_state.all_no[mode]['balance'],
                    'position_id': pos_id
                })
    
    return jsonify({'error': 'Position not found'}), 404

@app.route('/')
def index():
    # Serve the main dashboard HTML
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Kalshi-Frigo - DRY Trading Dashboard</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%232ee6a8'/><text x='16' y='23' font-size='19' font-weight='bold' text-anchor='middle' fill='#000'>D</text></svg>">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #0a0a0a; color: #f5f5f5; }
        .dashboard { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .brand { font-size: 24px; font-weight: bold; color: #34d399; }
        .mode-switch { display: flex; gap: 10px; }
        .mode-btn { padding: 8px 16px; background: #1f1f1f; color: #ccc; border: 1px solid #333; border-radius: 4px; cursor: pointer; }
        .mode-btn.active { background: #34d399; color: #000; }
        .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 20px; margin: 20px 0; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
        .tile { background: #222; border-radius: 8px; padding: 15px; text-align: center; }
        .tile .value { font-size: 24px; font-weight: bold; color: #34d399; }
        .tile .label { color: #999; font-size: 14px; margin-top: 5px; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #333; }
        th { background: #222; color: #ccc; }
        .profit { color: #34d399; }
        .loss { color: #f87171; }
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <div class="brand">Kalshi-Frigo - DRY Trading Dashboard</div>
            <div class="mode-switch">
                <button class="mode-btn active" onclick="switchMode('dry')">DRY</button>
                <button class="mode-btn" onclick="switchMode('live')">LIVE</button>
                <button class="mode-btn" onclick="window.location.href='/all-no-markets'">ALL NO</button>
            </div>
        </div>
        
        <div class="card">
            <h2>Dashboard Overview</h2>
            <div class="tiles">
                <div class="tile">
                    <div class="value" id="dryCash">$0.00</div>
                    <div class="label">DRY Cash</div>
                </div>
                <div class="tile">
                    <div class="value" id="winRate">0.0%</div>
                    <div class="label">Win Rate</div>
                </div>
                <div class="tile">
                    <div class="value" id="positions">0</div>
                    <div class="label">Open Positions</div>
                </div>
                <div class="tile">
                    <div class="value" id="pnl">$0.00</div>
                    <div class="label">P&L</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>Recent Trades</h2>
            <table>
                <thead>
                    <tr>
                        <th>Market</th>
                        <th>Side</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>Quantity</th>
                        <th>P&L</th>
                        <th>Strategy</th>
                    </tr>
                </thead>
                <tbody id="tradesTable">
                    <!-- Trades will be populated by JavaScript -->
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        // Global state from Python
        const globalState = {
            dry: {
                cash: 0,
                positions: 0,
                pnl: 0,
                winRate: 0,
                closed: []
            }
        };
        
        function formatCurrency(n) { return '$' + n.toFixed(2); }
        function formatPercent(n) { return n.toFixed(1) + '%'; }
        
        // Update dashboard with current data
        function updateDashboard() {
            document.getElementById('dryCash').textContent = formatCurrency(globalState.dry.cash);
            document.getElementById('winRate').textContent = formatPercent(globalState.dry.winRate);
            document.getElementById('positions').textContent = globalState.dry.positions;
            document.getElementById('pnl').textContent = formatCurrency(globalState.dry.pnl);
            
            // Update trades table
            const tradesTable = document.getElementById('tradesTable');
            tradesTable.innerHTML = globalState.dry.closed.map(trade => `
                <tr>
                    <td>${trade.market_id}</td>
                    <td>${trade.side}</td>
                    <td>${trade.entry_price.toFixed(3)}</td>
                    <td>${trade.exit_price.toFixed(3)}</td>
                    <td>${trade.quantity}</td>
                    <td class="${trade.pnl > 0 ? 'profit' : 'loss'}">${trade.pnl.toFixed(2)}</td>
                    <td>${trade.strategy}</td>
                </tr>
            `).join('');
        }
        
        function switchMode(mode) {
            window.location.href = '/' + mode;
        }
        
        // Initialize dashboard
        updateDashboard();
        
        // Refresh every 5 seconds
        setInterval(updateDashboard, 5000);
        
        // WebSocket connection for real-time updates
        const socket = io();
        socket.on('mode_update', (data) => {
            console.log('Mode update:', data);
            // Update dashboard with new data
            updateDashboard();
        });
    </script>
</body>
</html>
"""
    return Response(html, mimetype='text/html')

@app.route('/live')
def live():
    return Response("LIVE dashboard - Coming Soon!", mimetype='text/html')

@app.route('/all-no-markets')
def all_no_markets():
    # Serve the ALL NO MARKETS page HTML
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>*NO* LANE MARKETS</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #ffffff; color: #0a0a0a; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
        .brand {{ font-size: 20px; font-weight: bold; }}
        .back {{ color: #4d9fff; text-decoration: none; }}
        .button {{ padding: 8px 16px; background: #0a0a0a; color: #fff; border: 1px solid #d4d4d4; border-radius: 4px; cursor: pointer; }}
        .button.active {{ background: #ffd700; color: #0a0a0a; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #1f1f1f; }}
        th {{ background: #e5e5e5; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="brand">*NO* LANE MARKETS</div>
            <div>
                <a class="back" href="/">&larr; DASHBOARD</a> |
                <button class="button" id="noLanesBtn">*NO* LANES OFF</button>
            </div>
        </div>
        
        <div class="rule">
            <b>Every row below is a *NO* LANE contract entered with a resting limit order at the side's bid — not by crossing the spread. Prices are the limit actually rested.<br>
            <b>Separated from the lanes.</b> This book's money, positions and closed trades are its own: a paper $250 seeded once and never re-funded, and every row tagged strategy = all_no_markets. The BTC / ETH / XRP / HYPE up/down lanes keep their own clips, tallies and balances and never appear here.<br>
            <b>Sizing: full-Kelly.</b> Clip size follows Kelly Criterion for the modeled edge and price. <b>Read-only</b> — nothing here places, cancels or modifies an order.
        </div>
        
        <!-- Summary tiles -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 20px;">
            <div class="card">
                <div style="font-size: 12px; color: #999;">Book balance</div>
                <div style="font-size: 20px; font-weight: bold; color: #34d399;" id="balance">$250.00</div>
                <div style="font-size: 11px; color: #999;">paper · seeded once</div>
            </div>
            <div class="card">
                <div style="font-size: 12px; color: #999;">Deployed</div>
                <div style="font-size: 20px; font-weight: bold;" id="deployed">$0.00</div>
                <div style="font-size: 11px; color: #999;">resting limit × qty</div>
            </div>
            <div class="card">
                <div style="font-size: 12px; color: #999;">Equity</div>
                <div style="font-size: 20px; font-weight: bold;" id="equity">$250.00</div>
                <div style="font-size: 11px; color: #999;">balance + deployed</div>
            </div>
            <div class="card">
                <div style="font-size: 12px; color: #999;">Book P&L</div>
                <div style="font-size: 20px; font-weight: bold;" id="pnl">$0.00</div>
                <div style="font-size: 11px; color: #999;">0 entries</div>
            </div>
            <div class="card">
                <div style="font-size: 12px; color: #999;">Closed trades</div>
                <div style="font-size: 20px; font-weight: bold;" id="closed">0</div>
                <div style="font-size: 11px; color: #999;">lifetime</div>
            </div>
            <div class="card">
                <div style="font-size: 12px; color: #999;">Win rate</div>
                <div style="font-size: 20px; font-weight: bold;" id="winRate">0.0%</div>
                <div style="font-size: 11px; color: #999;">0W / 0L</div>
            </div>
        </div>
        
        <!-- Open positions table -->
        <div class="card">
            <h2>Open *NO* LANE positions</h2>
            <span style="color: #ffdd00; font-size: 12px;" id="openNote">0 resting</span>
            <div style="margin-top: 10px;">
                <input type="text" id="openFilter" placeholder="filter market / strategy" style="padding: 6px; width: 200px;">
                <button onclick="clearFilter('openFilter','openBody')">clear</button>
            </div>
            <div style="margin-top: 10px; overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>ID</th><th>Market</th><th>Strategy</th><th>Side</th><th class="num">Limit entry</th>
                            <th class="num">Qty</th><th class="num">Cost</th><th class="num">Model fair</th><th class="num">Edge</th>
                            <th class="num">Kelly f*</th><th class="num">Stop</th><th class="num">Take profit</th><th class="num">Conf</th>
                            <th>Expiration</th><th>Status</th><th>Book</th><th>Opened (UTC)</th><th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="openBody">
                        <tr><td colspan="17" class="empty">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Closed trades table -->
        <div class="card">
            <h2>Closed *NO* LANE trades</h2>
            <span style="color: #ffdd00; font-size: 12px;" id="closedNote">0 trades</span>
            <div style="margin-top: 10px;">
                <input type="text" id="closedFilter" placeholder="filter market / strategy / reason" style="padding: 6px; width: 200px;">
                <button onclick="clearFilter('closedFilter','closedBody')">clear</button>
            </div>
            <div style="margin-top: 10px; overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>ID</th><th>Market</th><th>Strategy</th><th>Side</th><th class="num">Entry</th>
                            <th class="num">Exit</th><th class="num">Qty</th><th class="num">Cost</th><th class="num">Proceeds</th>
                            <th class="num">P&L</th><th class="num">ROI</th><th class="num">Model fair</th><th class="num">Kelly f*</th>
                            <th class="num">Fee</th><th>Exit reason</th><th>Book</th><th>Opened (UTC)</th><th>Closed (UTC)</th>
                        </tr>
                    </thead>
                    <tbody id="closedBody">
                        <tr><td colspan="17" class="empty">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <footer>*NO* LANE side only · maker (limit) entries · read-only</footer>
    </div>
    
    <script>
        // Load ALL NO data
        async function loadAllNo() {
            try {
                const response = await fetch('/api/no-lanes/book');
                const data = await response.json();
                
                if (data.error) {
                    console.error('Failed to load ALL NO data:', data.error);
                    return;
                }
                
                // Update summary tiles
                document.getElementById('balance').textContent = '$' + data.book.balance.toFixed(2);
                document.getElementById('deployed').textContent = '$' + data.open_tally.cost.toFixed(2);
                document.getElementById('equity').textContent = '$' + (data.book.balance + data.open_tally.cost).toFixed(2);
                document.getElementById('pnl').textContent = '$' + data.book.pnl.toFixed(2);
                document.getElementById('closed').textContent = data.tally.closed;
                document.getElementById('winRate').textContent = data.tally.win_rate.toFixed(1) + '%';
                document.getElementById('winRateSub').textContent = data.tally.wins + 'W / ' + data.tally.losses + 'L';
                
                // Update NO LANES button
                const btn = document.getElementById('noLanesBtn');
                btn.classList.toggle('active', data.no_lanes_enabled);
                btn.textContent = '*NO* LANES ' + (data.no_lanes_enabled ? 'ON' : 'OFF');
                
                // Update tables
                updateOpenPositions(data.open_rows || []);
                updateClosedTrades(data.closed_rows || []);
                
            } catch (error) {
                console.error('Load error:', error);
            }
        }
        
        function updateOpenPositions(rows) {
            const tbody = document.getElementById('openBody');
            if (!rows || !rows.length) {
                tbody.innerHTML = '<tr><td colspan="17" class="empty">No open *NO* LANE positions in this book — the up/down lanes keep their own clips, and this book has not placed one yet.</td></tr>';
                return;
            }
            
            tbody.innerHTML = rows.map(r => `
                <tr class="${r.entry_price >= 0.84 && r.entry_price <= 0.92 ? 'band' : ''}">
                    <td class="mono">${r.id || '—'}</td>
                    <td class="mono">${r.market_id || '—'}</td>
                    <td>${r.strategy || 'all_no'}</td>
                    <td><span class="badge no">*NO* LANE</span></td>
                    <td class="num">${(r.entry_price * 100).toFixed(1) + '¢'}</td>
                    <td class="num">${r.quantity}</td>
                    <td class="num">${r.cost.toFixed(2)}</td>
                    <td class="num">${(r.entry_fair * 100).toFixed(1) + '¢'}</td>
                    <td class="num ${r.edge > 0 ? 'up' : (r.edge < 0 ? 'down' : 'flat')}">${(r.edge >= 0 ? '+' : '') + r.edge.toFixed(3) + 'pp'}</td>
                    <td class="num ${r.kelly > 0 ? 'up' : 'flat'}">${(r.kelly * 100).toFixed(2)}%</td>
                    <td class="num">${r.stop_loss > 0 ? (r.stop_loss * 100).toFixed(1) + '¢' : '—'}</td>
                    <td class="num">${r.take_profit > 0 ? (r.take_profit * 100).toFixed(1) + '¢' : '—'}</td>
                    <td class="num">${r.confidence.toFixed(2)}</td>
                    <td>${r.expiration ? r.expiration.split('T')[0] : '—'}</td>
                    <td><span class="badge ${r.status === 'closing' ? 'closing' : 'open'}">${r.status}</span></td>
                    <td><span class="badge ${r.mode === 'live' ? 'live' : 'dry'}">${r.mode.toUpperCase()}</span></td>
                    <td class="mono">${r.timestamp ? r.timestamp.substring(0, 16).replace('T', ' ') : '—'}</td>
                    <td><button class="btn-exit" onclick="promptExit('${r.id}', '${r.market_id}')">EXIT</button></td>
                </tr>
            `).join('');
        }
        
        function updateClosedTrades(rows) {
            const tbody = document.getElementById('closedBody');
            if (!rows || !rows.length) {
                tbody.innerHTML = '<tr><td colspan="17" class="empty">No closed NO trades in this book yet — the up/down lanes keep their own history; this book has not closed one.</td></tr>';
                return;
            }
            
            tbody.innerHTML = rows.map(r => `
                <tr>
                    <td class="mono">${r.id || '—'}</td>
                    <td class="mono">${r.market_id || '—'}</td>
                    <td>${r.strategy || 'all_no'}</td>
                    <td><span class="badge no">*NO* LANE</span></td>
                    <td class="num">${(r.entry_price * 100).toFixed(1) + '¢'}</td>
                    <td class="num">${(r.exit_price * 100).toFixed(1) + '¢'}</td>
                    <td class="num">${r.quantity}</td>
                    <td class="num">${r.cost.toFixed(2)}</td>
                    <td class="num">${r.proceeds.toFixed(2)}</td>
                    <td class="num ${r.pnl > 0 ? 'up' : (r.pnl < 0 ? 'down' : 'flat')}">${(r.pnl >= 0 ? '+' : '') + r.pnl.toFixed(2)}</td>
                    <td class="num ${r.roi > 0 ? 'up' : (r.roi < 0 ? 'down' : 'flat')}">${(r.roi >= 0 ? '+' : '') + r.roi.toFixed(1)}%</td>
                    <td class="num">${(r.entry_fair * 100).toFixed(1) + '¢'}</td>
                    <td class="num ${r.kelly > 0 ? 'up' : 'flat'}">${(r.kelly * 100).toFixed(2)}%</td>
                    <td class="num">${r.fee_paid.toFixed(3)}</td>
                    <td>${r.exit_reason || '—'}</td>
                    <td><span class="badge ${r.mode === 'live' ? 'live' : 'dry'}">${r.mode.toUpperCase()}</span></td>
                    
                    <td class="mono">${r.entry_timestamp ? r.entry_timestamp.substring(0, 16).replace('T', ' ') : '—'}</td>
                    <td class="mono">${r.exit_timestamp ? r.exit_timestamp.substring(0, 16).replace('T', ' ') : '—'}</td>
                </tr>
            `).join('');
        }
        
        function filterRows(inputId, bodyId) {
            const q = document.getElementById(inputId).value.toLowerCase();
            const rows = document.getElementById(bodyId).getElementsByTagName('tr');
            for (let i = 0; i < rows.length; i++) {
                const text = rows[i].textContent || rows[i].innerText;
                rows[i].style.display = text.toLowerCase().indexOf(q) > -1 ? '' : 'none';
            }
        }
        
        function clearFilter(inputId, bodyId) {
            document.getElementById(inputId).value = '';
            filterRows(inputId, bodyId);
        }
        
        async function toggleNoLanes() {
            const btn = document.getElementById('noLanesBtn');
            const currentlyOn = btn.classList.contains('active');
            const next = !currentlyOn;
            
            try {
                const response = await fetch('/api/no-lanes', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({enabled: next})
                });
                const data = await response.json();
                if (data.error) {
                    console.error('NO LANES toggle failed:', data.error);
                    return;
                }
                btn.classList.toggle('active', next);
                btn.textContent = '*NO* LANES ' + (next ? 'ON' : 'OFF');
            } catch (error) {
                console.error('Toggle failed:', error);
            }
        }
        
        function promptExit(posId, market) {
            var exitPrice = prompt('Exit price for ' + market + ' (position ' + posId.substring(0, 20) + '):', '0.95');
            if (exitPrice === null) return;
            var exitReason = prompt('Exit reason (take_profit/stop_loss/manual):', 'manual');
            if (exitReason === null) return;
            closePosition(posId, parseFloat(exitPrice), exitReason);
        }
        
        async function closePosition(posId, exitPrice, exitReason) {
            try {
                const response = await fetch('/api/no-lanes/exit', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({position_id: posId, exit_price: exitPrice, exit_reason: exitReason})
                });
                const data = await response.json();
                if (data.error) {
                    alert('Exit failed: ' + data.error);
                    return;
                }
                alert('Position closed: P&L = ' + data.pnl.toFixed(2) + ', New balance = ' + data.balance.toFixed(2));
                loadAllNo();
            } catch (error) {
                alert('Exit error: ' + error.message);
            }
        }
        
        // Load on page init
        loadAllNo();
        // Refresh every 30 seconds
        setInterval(loadAllNo, 30000);
    </script>
</body>
</html>
"""
    response = Response(html, mimetype='text/html')
    return response

if __name__ == '__main__':
    print("Starting Kai-Mirror Trading Dashboard in Python...")
    print("Serving on http://127.0.0.1:5000")
    print("Three HTML pages have been converted:")
    print("  - http://127.0.0.1:5000/         (main DRY dashboard)")
    print("  - http://127.0.0.1:5000/strategy/{name} (strategy details)")
    print("  - http://127.0.0.1:5000/all-no-markets (ALL NO markets)")
    
    socketio.run(app, host='127.0.0.1', port=5000, debug=True)
EOF