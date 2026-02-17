/**
 * Styrene Mesh Explorer — vis-network graph visualization with SSE updates.
 */
(function () {
    'use strict';

    // --- State ---
    let network = null;
    let nodesDataSet = null;
    let edgesDataSet = null;
    let allNodes = [];   // raw API data
    let allEdges = [];
    let eventSource = null;

    // --- DOM refs ---
    const graphEl = document.getElementById('graph');
    const searchEl = document.getElementById('search');
    const filterTypeEl = document.getElementById('filter-type');
    const filterStatusEl = document.getElementById('filter-status');
    const showUnnamedEl = document.getElementById('show-unnamed');
    const nodeCountEl = document.getElementById('node-count');
    const activeCountEl = document.getElementById('active-count');
    const staleCountEl = document.getElementById('stale-count');
    const lostCountEl = document.getElementById('lost-count');
    const daemonStatusEl = document.getElementById('daemon-status');
    const statusTextEl = daemonStatusEl.querySelector('.status-text');
    const detailPanel = document.getElementById('detail-panel');
    const panelTitle = document.getElementById('panel-title');
    const panelBody = document.getElementById('panel-body');
    const panelClose = document.getElementById('panel-close');

    // --- Color + shape mapping ---
    const TYPE_COLORS = {
        styrene_node: '#39ff14',
        hub:          '#39ff14',
        rnode:        '#ffa94d',
        generic:      '#888888',
        unknown:      '#555555',
    };

    const TYPE_SHAPES = {
        styrene_node: 'dot',
        hub:          'dot',
        rnode:        'diamond',
        generic:      'dot',
        unknown:      'dot',
    };

    const TYPE_ICONS = {
        styrene_node: 'S',
        hub:          'H',
        rnode:        'R',
        generic:      '',
        unknown:      '',
    };

    const STATUS_OPACITY = {
        active: 1.0,
        stale:  0.6,
        lost:   0.25,
    };

    const EDGE_COLORS = {
        RNodeInterface:        { color: '#ffa94d', dashes: [5, 5] },
        TCPClientInterface:    { color: '#39ff14', dashes: false },
        TCPServerInterface:    { color: '#39ff14', dashes: false },
        AutoInterface:         { color: '#4dd0e1', dashes: [2, 4] },
        LocalInterface:        { color: '#22cc00', dashes: false },
        KISSInterface:         { color: '#ffa94d', dashes: [5, 5] },
    };

    const DEFAULT_EDGE = { color: '#1a8c00', dashes: false };

    // --- vis-network options ---
    const NETWORK_OPTIONS = {
        nodes: {
            font: {
                face: 'VT323, Share Tech Mono, monospace',
                size: 14,
                color: '#39ff14',
                strokeWidth: 0,
            },
            borderWidth: 1,
            borderWidthSelected: 2,
        },
        edges: {
            width: 1,
            smooth: {
                type: 'continuous',
                roundness: 0.3,
            },
            arrows: { to: { enabled: false } },
            font: {
                face: 'VT323, Share Tech Mono, monospace',
                size: 10,
                color: '#0e4400',
                strokeWidth: 0,
            },
        },
        physics: {
            solver: 'barnesHut',
            barnesHut: {
                gravitationalConstant: -3000,
                centralGravity: 0.15,
                springLength: 120,
                springConstant: 0.04,
                damping: 0.15,
                avoidOverlap: 0.2,
            },
            stabilization: {
                enabled: true,
                iterations: 200,
                updateInterval: 25,
            },
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            navigationButtons: false,
            keyboard: { enabled: true },
        },
        layout: {
            improvedLayout: true,
        },
    };

    // --- Initialize ---
    function init() {
        nodesDataSet = new vis.DataSet();
        edgesDataSet = new vis.DataSet();

        network = new vis.Network(graphEl, {
            nodes: nodesDataSet,
            edges: edgesDataSet,
        }, NETWORK_OPTIONS);

        network.on('click', onNodeClick);
        network.on('deselectNode', () => hideDetailPanel());

        panelClose.addEventListener('click', () => {
            hideDetailPanel();
            network.unselectAll();
        });

        searchEl.addEventListener('input', applyFilters);
        filterTypeEl.addEventListener('change', applyFilters);
        filterStatusEl.addEventListener('change', applyFilters);
        showUnnamedEl.addEventListener('change', () => fetchTopology());

        fetchTopology();
        fetchStatus();
        connectSSE();

        // Periodic status refresh
        setInterval(fetchStatus, 15000);
    }

    // --- API calls ---
    async function fetchTopology() {
        try {
            const unnamed = showUnnamedEl.checked;
            const resp = await fetch(`/api/mesh/topology?include_unnamed=${unnamed}`);
            const data = await resp.json();
            allNodes = data.nodes || [];
            allEdges = data.edges || [];
            applyFilters();
            updateStats();
        } catch (err) {
            console.error('Failed to fetch topology:', err);
        }
    }

    async function fetchStatus() {
        try {
            const resp = await fetch('/api/mesh/status');
            const data = await resp.json();
            setDaemonStatus('connected', formatUptime(data.uptime));
        } catch {
            setDaemonStatus('error', 'OFFLINE');
        }
    }

    // --- SSE ---
    function connectSSE() {
        if (eventSource) eventSource.close();
        eventSource = new EventSource('/events');

        eventSource.addEventListener('device-updated', (e) => {
            try {
                const device = JSON.parse(e.data);
                mergeNode(device);
                updateStats();
            } catch (err) {
                console.error('SSE parse error:', err);
            }
        });

        eventSource.onopen = () => setDaemonStatus('connected', 'LIVE');
        eventSource.onerror = () => setDaemonStatus('error', 'SSE ERROR');
    }

    function mergeNode(device) {
        const idx = allNodes.findIndex(n => n.id === device.id);
        if (idx >= 0) {
            allNodes[idx] = { ...allNodes[idx], ...device };
        } else {
            allNodes.push(device);
        }
        applyFilters();
    }

    // --- Filtering ---
    function applyFilters() {
        const query = searchEl.value.toLowerCase();
        const typeFilter = filterTypeEl.value;
        const statusFilter = filterStatusEl.value;

        const filtered = allNodes.filter(n => {
            if (typeFilter !== 'all' && n.type !== typeFilter) return false;
            if (statusFilter !== 'all' && n.status !== statusFilter) return false;
            if (query && !n.label.toLowerCase().includes(query) && !n.id.toLowerCase().includes(query)) return false;
            return true;
        });

        const visibleIds = new Set(filtered.map(n => n.id));

        // Update nodes DataSet
        const visNodes = filtered.map(toVisNode);
        nodesDataSet.clear();
        nodesDataSet.add(visNodes);

        // Update edges DataSet — only edges between visible nodes
        const visEdges = allEdges
            .filter(e => visibleIds.has(e.from) && visibleIds.has(e.to))
            .map(toVisEdge);
        edgesDataSet.clear();
        edgesDataSet.add(visEdges);
    }

    function toVisNode(n) {
        const opacity = STATUS_OPACITY[n.status] || 0.4;
        const baseColor = TYPE_COLORS[n.type] || '#555555';
        const color = applyOpacity(baseColor, opacity);
        const size = n.type === 'hub' ? 25 : (n.type === 'styrene_node' ? 18 : 12);
        const icon = TYPE_ICONS[n.type] || '';

        return {
            id: n.id,
            label: icon ? `${icon} ${n.label}` : n.label,
            shape: TYPE_SHAPES[n.type] || 'dot',
            size: size,
            color: {
                background: color,
                border: color,
                highlight: { background: baseColor, border: baseColor },
                hover: { background: baseColor, border: baseColor },
            },
            font: {
                color: color,
                size: n.type === 'hub' ? 16 : 13,
            },
            title: `${n.label}\nType: ${n.type}\nStatus: ${n.status}\nLast seen: ${formatTimestamp(n.last_seen)}\nAnnounces: ${n.announce_count}`,
            _raw: n,
        };
    }

    function toVisEdge(e) {
        const style = EDGE_COLORS[e.interface_type] || DEFAULT_EDGE;
        const edgeId = `${e.from}->${e.to}`;
        return {
            id: edgeId,
            from: e.from,
            to: e.to,
            color: { color: style.color, opacity: 0.5 },
            dashes: style.dashes,
            width: e.hops === 0 ? 2 : 1,
            title: [
                e.interface_type || 'unknown',
                e.interface_name ? `(${e.interface_name})` : '',
                `${e.hops} hop${e.hops !== 1 ? 's' : ''}`,
                e.bitrate ? `${(e.bitrate / 1000).toFixed(0)} kbps` : '',
            ].filter(Boolean).join(' | '),
        };
    }

    // --- Detail panel ---
    function onNodeClick(params) {
        if (!params.nodes.length) {
            hideDetailPanel();
            return;
        }
        const nodeId = params.nodes[0];
        const node = allNodes.find(n => n.id === nodeId);
        if (!node) return;

        panelTitle.textContent = node.label;
        panelBody.innerHTML = '';

        const rows = [
            ['TYPE', node.type],
            ['STATUS', node.status],
            ['LAST SEEN', formatTimestamp(node.last_seen)],
            ['ANNOUNCES', node.announce_count],
            ['VERSION', node.version || '--'],
            ['CAPABILITIES', (node.capabilities || []).join(', ') || '--'],
        ];

        rows.forEach(([label, value]) => {
            const row = document.createElement('div');
            row.className = 'detail-row';
            row.innerHTML = `<span class="label">${label}</span><span class="value">${value}</span>`;
            panelBody.appendChild(row);
        });

        const hashDiv = document.createElement('div');
        hashDiv.className = 'detail-hash';
        hashDiv.textContent = node.id;
        panelBody.appendChild(hashDiv);

        detailPanel.classList.remove('hidden');
    }

    function hideDetailPanel() {
        detailPanel.classList.add('hidden');
    }

    // --- Stats ---
    function updateStats() {
        nodeCountEl.textContent = allNodes.length;
        activeCountEl.textContent = allNodes.filter(n => n.status === 'active').length;
        staleCountEl.textContent = allNodes.filter(n => n.status === 'stale').length;
        lostCountEl.textContent = allNodes.filter(n => n.status === 'lost').length;
    }

    function setDaemonStatus(state, text) {
        daemonStatusEl.className = 'status-badge ' + state;
        statusTextEl.textContent = text;
    }

    // --- Helpers ---
    function applyOpacity(hex, opacity) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r},${g},${b},${opacity})`;
    }

    function formatTimestamp(ts) {
        if (!ts) return '--';
        const elapsed = Math.floor(Date.now() / 1000 - ts);
        if (elapsed < 60) return elapsed + 's ago';
        if (elapsed < 3600) return Math.floor(elapsed / 60) + 'm ago';
        if (elapsed < 86400) return Math.floor(elapsed / 3600) + 'h ago';
        return Math.floor(elapsed / 86400) + 'd ago';
    }

    function formatUptime(seconds) {
        if (!seconds && seconds !== 0) return '--';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        return `UP ${h}h${m}m`;
    }

    // --- Boot ---
    document.addEventListener('DOMContentLoaded', init);
})();
