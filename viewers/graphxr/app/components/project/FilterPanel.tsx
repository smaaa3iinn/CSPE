'use client';

import { useState, useEffect, useMemo } from 'react';

interface FilterPanelProps {
    nodes: any[];
    edges: any[];
    onFilterChange: (filters: { nodes: Set<string> | null, edges: Set<string> | null }) => void;
    onClose: () => void;
}

export default function FilterPanel({ nodes, edges, onFilterChange, onClose }: FilterPanelProps) {
    const [searchTerm, setSearchTerm] = useState('');
    const [activeNodeFilters, setActiveNodeFilters] = useState<Record<string, Set<string>>>({});
    const [activeEdgeFilters, setActiveEdgeFilters] = useState<Record<string, Set<string>>>({});
    const [activeTab, setActiveTab] = useState<'nodes' | 'edges' | 'topology'>('nodes');

    // Topology State
    const [sourceNodeId, setSourceNodeId] = useState('');
    const [targetNodeId, setTargetNodeId] = useState('');
    const [topologyMode, setTopologyMode] = useState<'neighbors' | 'path' | null>(null);
    const [hopCount, setHopCount] = useState(1);

    // Build Adjacency List for Topology Ops
    const adjacencyList = useMemo(() => {
        const adj: Record<string, string[]> = {};
        edges.forEach(edge => {
            if (!adj[edge.source]) adj[edge.source] = [];
            if (!adj[edge.target]) adj[edge.target] = [];
            adj[edge.source].push(edge.target);
            adj[edge.target].push(edge.source); // Undirected for now
        });
        return adj;
    }, [edges]);

    // Extract categories helper - supports nested 'attributes' object
    const extractCategories = (items: any[], ignoreKeys: string[]) => {
        const cats: Record<string, Set<string>> = {};

        const processValue = (key: string, value: any) => {
            if (ignoreKeys.includes(key)) return;
            if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
                if (!cats[key]) cats[key] = new Set();
                cats[key].add(String(value));
            }
        };

        items.forEach(item => {
            Object.entries(item).forEach(([key, value]) => {
                // Handle nested 'attributes' object
                if (key === 'attributes' && typeof value === 'object' && value !== null) {
                    Object.entries(value).forEach(([attrKey, attrValue]) => {
                        processValue(attrKey, attrValue);
                    });
                } else {
                    processValue(key, value);
                }
            });
        });

        return Object.entries(cats)
            .filter(([_, values]) => values.size > 1 && values.size < 50)
            .reduce((acc, [key, values]) => {
                acc[key] = Array.from(values).sort();
                return acc;
            }, {} as Record<string, string[]>);
    };

    const nodeCategories = useMemo(() =>
        extractCategories(nodes, ['id', 'x', 'y', 'z', 'color', 'label', 'vx', 'vy', 'vz', 'index', 'fx', 'fy', 'fz']),
        [nodes]);

    const edgeCategories = useMemo(() =>
        extractCategories(edges, ['source', 'target', 'id', 'weight', 'color', 'index']),
        [edges]);

    // Apply filters
    useEffect(() => {
        // 1. Topology (Nodes only/Priority)
        if (topologyMode) {
            const visibleIds = new Set<string>();
            // ... (Topology logic same as before, simplified for brevity here, assume it returns node set)
            if (topologyMode === 'neighbors' && sourceNodeId) {
                // BFS for N hops
                const queue: Array<[string, number]> = [[sourceNodeId, 0]];
                const visited = new Set([sourceNodeId]);
                visibleIds.add(sourceNodeId);

                while (queue.length > 0) {
                    const item = queue.shift();
                    if (!item) continue;
                    const [currentId, dist] = item;
                    if (dist >= hopCount) continue;

                    const neighbors = adjacencyList[currentId] || [];
                    for (const neighbor of neighbors) {
                        if (!visited.has(neighbor)) {
                            visited.add(neighbor);
                            visibleIds.add(neighbor);
                            queue.push([neighbor, dist + 1]);
                        }
                    }
                }
                onFilterChange({ nodes: visibleIds, edges: null }); // Topology doesn't filter edges explicitly yet
                return;
            }
            if (topologyMode === 'path' && sourceNodeId && targetNodeId) {
                // BFS Shortest Path
                const queue: string[][] = [[sourceNodeId]];
                const visited = new Set([sourceNodeId]);
                let found = false;
                while (queue.length > 0) {
                    const path = queue.shift();
                    if (!path) continue;
                    const node = path[path.length - 1];
                    if (node === targetNodeId) {
                        path.forEach(id => visibleIds.add(id));
                        found = true;
                        break;
                    }
                    const neighbors = adjacencyList[node] || [];
                    for (const neighbor of neighbors) {
                        if (!visited.has(neighbor)) {
                            visited.add(neighbor);
                            queue.push([...path, neighbor]);
                        }
                    }
                }
                onFilterChange({ nodes: found ? visibleIds : new Set(), edges: null });
                return;
            }
        }

        // 2. Attribute Filters
        const hasNodeFilters = searchTerm || Object.keys(activeNodeFilters).length > 0;
        const hasEdgeFilters = Object.keys(activeEdgeFilters).length > 0;

        let visibleNodes: Set<string> | null = null;
        let visibleEdges: Set<string> | null = null;

        if (hasNodeFilters) {
            visibleNodes = new Set();
            nodes.forEach(node => {
                let matches = true;
                if (searchTerm) {
                    const term = searchTerm.toLowerCase();
                    const idMatch = node.id.toLowerCase().includes(term);
                    const labelMatch = node.label?.toLowerCase().includes(term);
                    if (!idMatch && !labelMatch) matches = false;
                }
                if (matches) {
                    for (const [key, selectedValues] of Object.entries(activeNodeFilters)) {
                        if (selectedValues.size > 0) {
                            // Check both top-level and nested attributes
                            const topLevelValue = node[key];
                            const nestedValue = node.attributes?.[key];
                            const value = topLevelValue !== undefined ? topLevelValue : nestedValue;

                            if (!selectedValues.has(String(value))) {
                                matches = false;
                                break;
                            }
                        }
                    }
                }
                if (matches && visibleNodes) visibleNodes.add(node.id);
            });
        }

        if (hasEdgeFilters) {
            visibleEdges = new Set();
            edges.forEach(edge => {
                let matches = true;
                for (const [key, selectedValues] of Object.entries(activeEdgeFilters)) {
                    if (selectedValues.size > 0 && !selectedValues.has(String(edge[key]))) {
                        matches = false; break;
                    }
                }
                if (matches) {
                    // Unique edge ID is often simpler if we use index or a constructed ID
                    // Assuming GraphRenderer can handle "edges that match criteria".
                    // Ideally we pass a Set of Edge Indices or Source-Target pairs? 
                    // Let's pass a constructed ID "source-target" which is common, but index is safer if available.
                    // For now let's assume filtering by source-target key or index. 
                    // GraphRenderer usually iterates edges. 
                    // Let's assume we pass a Set of Edge Objects or similar? No, Set<string> is requested.
                    // IMPORTANT: GraphRenderer typically filters edges if BOTH nodes are visible.
                    // Here we ADDITIONALLY want to filter edges based on THEIR attributes.
                    // Let's use a unique key. If edges don't have IDs, we might need to rely on index?
                    // Let's assume edges have IDs or we use `${edge.source}-${edge.target}` as a fallback key if ID missing.
                    // But wait, the edge object from graph_service usually doesn't have an ID unless GEXF.
                    // Let's use `${edge.source}-${edge.target}` as convention for now.
                    if (visibleEdges) visibleEdges.add(edge.id || `${edge.source}-${edge.target}`);
                }
            });
        }

        onFilterChange({ nodes: visibleNodes, edges: visibleEdges });

    }, [searchTerm, activeNodeFilters, activeEdgeFilters, nodes, edges, onFilterChange, topologyMode, sourceNodeId, targetNodeId, hopCount, adjacencyList]);

    const toggleFilter = (type: 'nodes' | 'edges', category: string, value: string) => {
        const setter = type === 'nodes' ? setActiveNodeFilters : setActiveEdgeFilters;
        setter(prev => {
            const newFilters = { ...prev };
            if (!newFilters[category]) newFilters[category] = new Set();
            if (newFilters[category].has(value)) {
                newFilters[category].delete(value);
                if (newFilters[category].size === 0) delete newFilters[category];
            } else {
                newFilters[category].add(value);
            }
            return newFilters;
        });
    };

    const resetFilters = () => {
        setSearchTerm('');
        setActiveNodeFilters({});
        setActiveEdgeFilters({});
        setTopologyMode(null);
        setSourceNodeId('');
        setTargetNodeId('');
        onFilterChange({ nodes: null, edges: null });
        setActiveTab('nodes');
    };

    return (
        <div className="fixed z-50 w-80 flex flex-col max-h-[70vh] animate-slide-up rounded-xl border border-surface-50/10 bg-surface-950/95 backdrop-blur-xl shadow-2xl"
            style={{ left: '2rem', bottom: '6rem' }}>

            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-surface-50/10 bg-surface-950/95 rounded-t-xl shrink-0">
                <h3 className="text-lg font-bold text-surface-50 flex items-center gap-2">
                    <svg className="w-5 h-5 text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                    </svg>
                    Filtres
                </h3>
                <div className="flex items-center gap-2">
                    <div className="group relative">
                        <svg className="w-5 h-5 text-surface-400 cursor-help" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <div className="absolute right-0 top-full mt-2 w-64 p-3 rounded-lg bg-surface-800 border border-surface-50/10 shadow-xl opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50 text-xs text-surface-200">
                            <strong>Guide des Filtres:</strong>
                            <ul className="list-disc pl-4 mt-1 space-y-1">
                                <li>Recherchez par ID ou Label.</li>
                                <li>Cliquez sur les tags pour filtrer par attribut.</li>
                                <li>Utilisez l&apos;onglet &apos;Topologie&apos; pour explorer les voisins.</li>
                            </ul>
                        </div>
                    </div>
                    {(searchTerm || Object.keys(activeNodeFilters).length > 0 || Object.keys(activeEdgeFilters).length > 0 || topologyMode) && (
                        <button onClick={resetFilters} className="text-xs font-medium text-primary-400 hover:text-primary-300 transition-colors">
                            Réinitialiser
                        </button>
                    )}
                    <button onClick={onClose} className="rounded-full p-1 text-surface-400 hover:bg-surface-50/10 hover:text-surface-50 transition-colors cursor-pointer">
                        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>
            </div>

            {/* Tabs */}
            <div className="flex border-b border-surface-50/10">
                {(['nodes', 'edges', 'topology'] as const).map(tab => (
                    <button
                        key={tab}
                        onClick={() => { setActiveTab(tab); if (tab !== 'topology') setTopologyMode(null); }}
                        className={`flex-1 py-3 text-sm font-medium transition-colors cursor-pointer capitalize ${activeTab === tab
                            ? 'text-primary-400 border-b-2 border-primary-400 bg-surface-50/5'
                            : 'text-surface-400 hover:text-surface-200'
                            }`}
                    >
                        {tab === 'nodes' ? 'Nœuds' : tab === 'edges' ? 'Liens' : 'Topologie'}
                    </button>
                ))}
            </div>

            {/* Content */}
            <div className="overflow-y-auto p-4 space-y-6 custom-scrollbar flex-1 min-h-0">
                {activeTab === 'nodes' && (
                    <>
                        <div className="space-y-2">
                            <label className="text-xs font-bold uppercase tracking-wider text-surface-400">Recherche</label>
                            <input
                                type="text"
                                placeholder="ID ou Label..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                className="w-full bg-surface-900/50 border border-surface-50/10 rounded-lg px-4 py-2 text-sm text-surface-50 placeholder-surface-500 focus:outline-none focus:border-primary-500/50"
                            />
                        </div>
                        {Object.entries(nodeCategories).map(([category, values]) => (
                            <div key={category} className="space-y-2">
                                <div className="flex items-center justify-between">
                                    <label className="text-xs font-bold uppercase tracking-wider text-primary-400">{category}</label>
                                    <span className="text-[10px] bg-surface-50/10 px-1.5 py-0.5 rounded text-surface-400">{values.length}</span>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {values.map(value => (
                                        <button
                                            key={value}
                                            onClick={() => toggleFilter('nodes', category, value)}
                                            className={`text-xs px-3 py-1.5 rounded-full border transition-all ${activeNodeFilters[category]?.has(value)
                                                ? 'bg-primary-500/20 border-primary-500/50 text-primary-100'
                                                : 'bg-surface-50/5 border-surface-50/10 text-surface-400 hover:border-surface-50/30 hover:text-surface-200'}`}
                                        >
                                            {value}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </>
                )}

                {activeTab === 'edges' && (
                    <>
                        {Object.keys(edgeCategories).length === 0 && (
                            <div className="text-center py-8 text-surface-500 text-sm italic">
                                Aucun attribut de lien filtrable détecté.
                            </div>
                        )}
                        {Object.entries(edgeCategories).map(([category, values]) => (
                            <div key={category} className="space-y-2">
                                <div className="flex items-center justify-between">
                                    <label className="text-xs font-bold uppercase tracking-wider text-purple-400">{category}</label>
                                    <span className="text-[10px] bg-surface-50/10 px-1.5 py-0.5 rounded text-surface-400">{values.length}</span>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {values.map(value => (
                                        <button
                                            key={value}
                                            onClick={() => toggleFilter('edges', category, value)}
                                            className={`text-xs px-3 py-1.5 rounded-full border transition-all ${activeEdgeFilters[category]?.has(value)
                                                ? 'bg-purple-500/20 border-purple-500/50 text-purple-100'
                                                : 'bg-surface-50/5 border-surface-50/10 text-surface-400 hover:border-surface-50/30 hover:text-surface-200'}`}
                                        >
                                            {value}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </>
                )}

                {activeTab === 'topology' && (
                    <div className="space-y-6">
                        {/* Neighbors Filter */}
                        <div className="relative group rounded-xl border border-primary-500/20 bg-surface-900/40 p-4 transition-all hover:bg-surface-900/60 hover:shadow-lg hover:shadow-primary-500/5 hover:-translate-y-0.5">
                            <div className="absolute inset-0 bg-gradient-to-br from-primary-500/5 to-transparent rounded-xl pointer-events-none" />

                            <div className="relative space-y-4">
                                <div className="flex items-center gap-2 mb-2">
                                    <div className="p-1.5 rounded-lg bg-primary-500/10 text-primary-400">
                                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                                        </svg>
                                    </div>
                                    <label className="text-xs font-bold uppercase tracking-wider text-primary-300">Analyse de Voisinage</label>
                                </div>

                                <div className="space-y-1">
                                    <span className="text-[10px] text-surface-400 font-medium uppercase tracking-wide ml-1">Noeud Central</span>
                                    <input
                                        type="text"
                                        list="node-ids"
                                        placeholder="Selectionnez un noeud..."
                                        value={sourceNodeId}
                                        onChange={(e) => setSourceNodeId(e.target.value)}
                                        className="w-full bg-surface-800/50 border border-surface-50/10 rounded-lg px-3 py-2.5 text-sm text-surface-50 placeholder-surface-500 focus:outline-none focus:border-primary-500/50 focus:ring-1 focus:ring-primary-500/20 transition-all"
                                    />
                                </div>

                                <div className="space-y-3 pt-2">
                                    <div className="flex items-center justify-between">
                                        <span className="text-[10px] text-surface-400 font-medium uppercase tracking-wide">Profondeur (Hops)</span>
                                        <span className="px-2 py-0.5 rounded-full bg-primary-500/10 text-primary-300 text-xs font-bold font-mono">
                                            {hopCount}
                                        </span>
                                    </div>
                                    <input
                                        type="range"
                                        min="1"
                                        max="5"
                                        value={hopCount}
                                        onChange={(e) => setHopCount(parseInt(e.target.value))}
                                        className="w-full h-1.5 bg-surface-50/10 rounded-full appearance-none cursor-pointer accent-primary-500 hover:accent-primary-400"
                                    />
                                    <div className="flex justify-between text-[10px] text-surface-500 px-1">
                                        <span>1</span>
                                        <span>5</span>
                                    </div>
                                </div>

                                <button
                                    onClick={() => setTopologyMode(topologyMode === 'neighbors' ? null : 'neighbors')}
                                    disabled={!sourceNodeId}
                                    className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-all flex items-center justify-center gap-2 shadow-sm
                                        ${topologyMode === 'neighbors'
                                            ? 'bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20'
                                            : !sourceNodeId
                                                ? 'bg-surface-50/5 text-surface-500 cursor-not-allowed border border-surface-50/5'
                                                : 'bg-primary-600/90 hover:bg-primary-500 text-white shadow-primary-500/20 hover:shadow-primary-500/40 hover:-translate-y-0.5'
                                        }`}
                                >
                                    {topologyMode === 'neighbors' ? (
                                        <>
                                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                            </svg>
                                            Désactiver
                                        </>
                                    ) : (
                                        <>
                                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                                            </svg>
                                            Explorer Voisins
                                        </>
                                    )}
                                </button>
                            </div>
                        </div>

                        {/* Path Filter */}
                        <div className="relative group rounded-xl border border-purple-500/20 bg-surface-900/40 p-4 transition-all hover:bg-surface-900/60 hover:shadow-lg hover:shadow-purple-500/5 hover:-translate-y-0.5">
                            <div className="absolute inset-0 bg-gradient-to-br from-purple-500/5 to-transparent rounded-xl pointer-events-none" />

                            <div className="relative space-y-4">
                                <div className="flex items-center gap-2 mb-2">
                                    <div className="p-1.5 rounded-lg bg-purple-500/10 text-purple-400">
                                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0121 18.382V7.618a1 1 0 01-.553-.894L15 4m0 13V4m0 0L9 7" />
                                        </svg>
                                    </div>
                                    <label className="text-xs font-bold uppercase tracking-wider text-purple-300">Chemin le plus court</label>
                                </div>

                                <div className="flex items-center gap-3">
                                    <div className="flex-1 space-y-1">
                                        <span className="text-[10px] text-surface-400 font-medium uppercase tracking-wide ml-1">Depart</span>
                                        <input
                                            type="text"
                                            list="node-ids"
                                            placeholder="Selectionnez..."
                                            value={sourceNodeId}
                                            onChange={(e) => setSourceNodeId(e.target.value)}
                                            className="w-full bg-surface-800/50 border border-surface-50/10 rounded-lg px-3 py-2 text-sm text-surface-50 placeholder-surface-500 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 transition-all text-center"
                                        />
                                    </div>
                                    <div className="pt-6 text-purple-400/50">
                                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                                        </svg>
                                    </div>
                                    <div className="flex-1 space-y-1">
                                        <span className="text-[10px] text-surface-400 font-medium uppercase tracking-wide ml-1">Arrivee</span>
                                        <input
                                            type="text"
                                            list="node-ids"
                                            placeholder="Selectionnez..."
                                            value={targetNodeId}
                                            onChange={(e) => setTargetNodeId(e.target.value)}
                                            className="w-full bg-surface-800/50 border border-surface-50/10 rounded-lg px-3 py-2 text-sm text-surface-50 placeholder-surface-500 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 transition-all text-center"
                                        />
                                    </div>
                                </div>

                                <button
                                    onClick={() => setTopologyMode(topologyMode === 'path' ? null : 'path')}
                                    disabled={!sourceNodeId || !targetNodeId}
                                    className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-all flex items-center justify-center gap-2 shadow-sm mt-2
                                        ${topologyMode === 'path'
                                            ? 'bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20'
                                            : (!sourceNodeId || !targetNodeId)
                                                ? 'bg-surface-50/5 text-surface-500 cursor-not-allowed border border-surface-50/5'
                                                : 'bg-purple-600/90 hover:bg-purple-500 text-white shadow-purple-500/20 hover:shadow-purple-500/40 hover:-translate-y-0.5'
                                        }`}
                                >
                                    {topologyMode === 'path' ? (
                                        <>
                                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                            </svg>
                                            Désactiver
                                        </>
                                    ) : (
                                        <>
                                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0121 18.382V7.618a1 1 0 01-.553-.894L15 4m0 13V4m0 0L9 7" />
                                            </svg>
                                            Trouver Chemin
                                        </>
                                    )}
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <div className="p-3 border-t border-surface-50/10 bg-surface-900/30 text-center">
                <p className="text-xs text-surface-400">
                    {(searchTerm || Object.keys(activeNodeFilters).length > 0 || Object.keys(activeEdgeFilters).length > 0 || topologyMode)
                        ? "Filtres actifs"
                        : "Affichage de tous les éléments"}
                </p>
            </div>

            <datalist id="node-ids">
                {nodes.slice(0, 2000).map(n => (
                    <option key={n.id} value={n.id}>{n.label || n.id}</option>
                ))}
            </datalist>
        </div >
    );
}
