'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Glasses, RotateCcw } from 'lucide-react';
import GraphSceneWeb, { GraphSceneRef } from '@/app/components/3DandXRComponents/Graph/GraphSceneWeb';
import GraphSceneXR from '@/app/components/3DandXRComponents/Graph/GraphSceneXR';
import DetailsPanel from '@/app/components/3DandXRComponents/UI/DetailsPanel';
import OverlayControls from '@/app/components/3DandXRComponents/UI/OverlayControls';
import FilterPanel from '@/app/components/project/FilterPanel';
import type { GraphProject } from '@/app/services/graphService';

type SelectionType = 'node' | 'edge' | null;

const SYNC_POLL_MS = 900;

function normalizeApiBase(value: string | null): string {
  return (value || '').replace(/\/$/, '');
}

function readViewFingerprint(project: GraphProject | null): string | null {
  const fp = project?.metadata?.view_fingerprint;
  return typeof fp === 'string' && fp.trim() ? fp : null;
}

export default function ViewerClient() {
  const searchParams = useSearchParams();
  const initialSession = searchParams.get('session');
  const syncClientId = searchParams.get('sync');
  const apiBase = normalizeApiBase(searchParams.get('api'));
  const embedded = searchParams.get('embedded') === '1';

  const [activeSessionId, setActiveSessionId] = useState<string | null>(initialSession);
  const [project, setProject] = useState<GraphProject | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [selectedItem, setSelectedItem] = useState<any>(null);
  const [selectionType, setSelectionType] = useState<SelectionType>(null);
  const [visibleNodeIds, setVisibleNodeIds] = useState<Set<string> | null>(null);
  const [visibleEdgeIds, setVisibleEdgeIds] = useState<Set<string> | null>(null);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [isVRMode, setIsVRMode] = useState(false);
  const [isInXR, setIsInXR] = useState(false);
  const [showLabels, setShowLabels] = useState(false);

  const graphSceneRef = useRef<GraphSceneRef>(null);
  const knownFingerprintRef = useRef<string | null>(null);
  const edgeList = useMemo(() => project?.graph_data?.edges || project?.graph_data?.links || [], [project]);

  useEffect(() => {
    let cancelled = false;

    async function loadSession(sessionId: string | null, background: boolean) {
      if (!sessionId) {
        setError('Missing CSPE graph session id.');
        setLoading(false);
        return;
      }
      if (!apiBase) {
        setError('Missing CSPE API base URL.');
        setLoading(false);
        return;
      }

      if (background) {
        setSyncing(true);
      } else {
        setLoading(true);
      }
      setError(null);
      try {
        const response = await fetch(
          `${apiBase}/api/transport/graph3d/session/${encodeURIComponent(sessionId)}`
        );
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || `CSPE graph session ${response.status}`);
        }
        const loadedProject = (await response.json()) as GraphProject;
        if (!cancelled) {
          setProject(loadedProject);
          knownFingerprintRef.current = readViewFingerprint(loadedProject);
          setSelectedItem(null);
          setSelectionType(null);
        }
      } catch (err) {
        if (!cancelled && !background) {
          setError(err instanceof Error ? err.message : 'Unable to load CSPE graph session.');
        }
      } finally {
        if (!cancelled) {
          if (background) {
            setSyncing(false);
          } else {
            setLoading(false);
          }
        }
      }
    }

    const background = project !== null;
    void loadSession(activeSessionId, background);
    return () => {
      cancelled = true;
    };
  }, [activeSessionId, apiBase]);

  useEffect(() => {
    if (!syncClientId || !apiBase) {
      return;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        const q = knownFingerprintRef.current
          ? `?fingerprint=${encodeURIComponent(knownFingerprintRef.current)}`
          : '';
        const response = await fetch(
          `${apiBase}/api/transport/graph3d/sync/${encodeURIComponent(syncClientId)}${q}`
        );
        if (!response.ok || cancelled) {
          return;
        }
        const data = (await response.json()) as {
          changed?: boolean;
          session_id?: string | null;
          fingerprint?: string | null;
        };
        if (!data.changed || !data.session_id || cancelled) {
          if (typeof data.fingerprint === 'string' && data.fingerprint) {
            knownFingerprintRef.current = data.fingerprint;
          }
          return;
        }
        if (data.session_id === activeSessionId) {
          if (typeof data.fingerprint === 'string' && data.fingerprint) {
            knownFingerprintRef.current = data.fingerprint;
          }
          return;
        }
        if (typeof data.fingerprint === 'string' && data.fingerprint) {
          knownFingerprintRef.current = data.fingerprint;
        }
        setActiveSessionId(data.session_id);
      } catch {
        /* offline or API down */
      }
    };

    void poll();
    const id = window.setInterval(() => void poll(), SYNC_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [syncClientId, apiBase, activeSessionId]);

  const handleResetCamera = useCallback(() => {
    graphSceneRef.current?.resetCamera();
  }, []);

  const handleFilterChange = useCallback((filters: { nodes: Set<string> | null; edges: Set<string> | null }) => {
    setVisibleNodeIds(filters.nodes);
    setVisibleEdgeIds(filters.edges);
  }, []);

  if (loading || error || !project) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface-950 px-6 text-white">
        <div className="max-w-lg rounded-3xl border border-white/10 bg-white/5 p-8 text-center shadow-2xl">
          <h1 className="text-2xl font-bold">CSPE 3D/VR Graph</h1>
          <p className="mt-3 text-sm text-surface-300">
            {loading ? 'Loading the prepared CSPE graph session...' : error || 'No graph session loaded.'}
          </p>
          {!loading && (
            <p className="mt-4 text-xs text-surface-500">
              Open this viewer from CSPE after computing a transport route.
            </p>
          )}
        </div>
      </main>
    );
  }

  return (
    <div className="relative h-screen w-full overflow-hidden bg-black">
      {syncing && (
        <div className="pointer-events-none absolute left-1/2 top-4 z-30 -translate-x-1/2 rounded-full border border-white/10 bg-black/60 px-4 py-1 text-xs text-white/80 backdrop-blur-md">
          Syncing transport view…
        </div>
      )}

      {isInXR && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-gradient-to-br from-surface-950 via-surface-900 to-surface-950">
          <div className="text-center">
            <div className="mx-auto mb-6 flex h-24 w-24 items-center justify-center rounded-full bg-primary-500/20 text-primary-400">
              <Glasses className="h-12 w-12" />
            </div>
            <h2 className="mb-2 text-2xl font-bold text-white">VR Session Active</h2>
            <p className="mb-6 max-w-sm text-gray-400">Look inside your headset to explore the CSPE graph.</p>
            <button
              onClick={() => window.location.reload()}
              className="rounded-full border border-red-500/30 bg-red-500/20 px-4 py-2 text-sm font-medium text-red-400 hover:bg-red-500/30"
            >
              Stop VR Session
            </button>
          </div>
        </div>
      )}

      <div className="absolute inset-0 z-0" style={{ touchAction: 'none' }}>
        {isVRMode ? (
          <GraphSceneXR
            ref={graphSceneRef}
            key="xr-scene"
            data={project.graph_data}
            onSelect={(data, type) => {
              setSelectedItem(data);
              setSelectionType(type);
            }}
            visibleNodeIds={visibleNodeIds}
            visibleEdgeIds={visibleEdgeIds}
            onXRStateChange={setIsInXR}
            showLabels={showLabels}
            onResetFilters={() => {
              setVisibleNodeIds(null);
              setVisibleEdgeIds(null);
            }}
            onToggleLabels={() => setShowLabels(prev => !prev)}
          />
        ) : (
          <GraphSceneWeb
            ref={graphSceneRef}
            key="web-scene"
            data={project.graph_data}
            onSelect={(data, type) => {
              setSelectedItem(data);
              setSelectionType(type);
            }}
            visibleNodeIds={visibleNodeIds}
            visibleEdgeIds={visibleEdgeIds}
            showLabels={showLabels}
          />
        )}
      </div>

      {!embedded && (
        <div className="absolute left-4 top-4 z-20 rounded-2xl border border-white/10 bg-black/50 p-4 text-white backdrop-blur-xl">
          <div className="text-sm text-surface-400">CSPE transport graph</div>
          <div className="max-w-xs truncate text-lg font-semibold">{project.name}</div>
          <div className="mt-2 text-xs text-surface-400">
            {project.graph_data.nodes?.length || 0} nodes · {edgeList.length} edges
            {project.metadata?.route_node_count ? ` · ${project.metadata.route_node_count} route nodes` : ''}
            {syncClientId ? ' · live sync' : ''}
          </div>
          <button
            onClick={() => window.close()}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-white/10 px-3 py-2 text-sm text-white hover:bg-white/20"
          >
            <RotateCcw className="h-4 w-4" />
            Back to CSPE
          </button>
        </div>
      )}

      {selectedItem && (
        <DetailsPanel
          data={selectedItem}
          type={selectionType}
          onClose={() => {
            setSelectedItem(null);
            setSelectionType(null);
          }}
        />
      )}

      {isFilterOpen && project.graph_data.nodes && (
        <FilterPanel
          nodes={project.graph_data.nodes}
          edges={edgeList}
          onFilterChange={handleFilterChange}
          onClose={() => setIsFilterOpen(false)}
        />
      )}

      {!isInXR && (
        <div className="absolute bottom-0 left-0 right-0 z-10 pb-8">
          <OverlayControls
            onResetCamera={handleResetCamera}
            onToggleVR={() => setIsVRMode(prev => !prev)}
            hideEdit
            hideShare
            placement={embedded ? 'right-center' : 'bottom-center'}
          >
            <button
              onClick={() => setShowLabels(prev => !prev)}
              className={`group relative flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-all hover:scale-105 ${showLabels
                ? 'border border-primary-500/50 bg-primary-500/20 text-white'
                : 'bg-white/5 text-gray-300 hover:bg-primary-500/20 hover:text-white'
                }`}
              title={showLabels ? 'Hide labels' : 'Show labels'}
            >
              <span className="hidden sm:inline">Labels</span>
            </button>
            <button
              onClick={() => setIsFilterOpen(prev => !prev)}
              className={`group relative flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-all hover:scale-105 ${isFilterOpen || visibleNodeIds !== null
                ? 'border border-primary-500/50 bg-primary-500/20 text-white'
                : 'bg-white/5 text-gray-300 hover:bg-primary-500/20 hover:text-white'
                }`}
              title="Filter graph"
            >
              <span className="hidden sm:inline">Filters</span>
            </button>
          </OverlayControls>
        </div>
      )}
    </div>
  );
}
