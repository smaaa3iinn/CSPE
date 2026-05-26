import { useState, useRef, useEffect } from 'react';
import { Download, FileJson, FileText, Table, Upload } from 'lucide-react';

interface OverlayControlsProps {
    onResetCamera: () => void;
    onToggleVR: () => void;
    onShare?: () => void;
    onEdit?: () => void;
    onExportReport?: () => void;
    onExportJSON?: () => void;
    onExportCSVNodes?: () => void;
    onExportCSVEdges?: () => void;
    onImportConfig?: () => void;
    children?: React.ReactNode;
    hideEdit?: boolean;
    hideShare?: boolean;
    placement?: 'bottom-center' | 'right-center';
}

export default function OverlayControls({
    onResetCamera,
    onToggleVR,
    onShare,
    onEdit,
    onExportReport,
    onExportJSON,
    onExportCSVNodes,
    onExportCSVEdges,
    onImportConfig,
    children,
    hideEdit = false,
    hideShare = false,
    placement = 'bottom-center'
}: OverlayControlsProps) {
    const [isExportOpen, setIsExportOpen] = useState(false);
    const exportRef = useRef<HTMLDivElement>(null);
    const handleImportClick = () => {
        if (onImportConfig) {
            onImportConfig();
        }
    };

    const chromeClass = placement === 'right-center'
        ? 'absolute right-4 top-1/2 flex -translate-y-1/2 flex-col gap-2 rounded-2xl border border-white/10 bg-black/40 p-2 backdrop-blur-2xl shadow-2xl items-stretch'
        : 'absolute bottom-6 left-1/2 flex -translate-x-1/2 transform gap-2 rounded-2xl border border-white/10 bg-black/40 p-2 backdrop-blur-2xl shadow-2xl items-center';
    const dividerClass = placement === 'right-center' ? 'h-px w-full bg-white/10' : 'w-px h-6 bg-white/10';

    return (
        <div className={chromeClass}>
            <button
                onClick={onResetCamera}
                className="group relative flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm text-gray-300 transition-all hover:bg-blue-500/20 hover:text-white hover:scale-105 cursor-pointer"
                title="Réinitialiser la vue"
            >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                <span className="hidden sm:inline">Reset</span>
            </button>

            <div className={dividerClass}></div>

            {children}

            {children && <div className={dividerClass}></div>}

            <button
                onClick={onToggleVR}
                className="group relative flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm text-gray-300 transition-all hover:bg-purple-500/20 hover:text-white hover:scale-105 cursor-pointer"
                title="Mode VR Immersif"
            >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <span className="hidden sm:inline">VR</span>
            </button>

            {!hideEdit && onEdit && (
                <>
                    <div className={dividerClass}></div>
                    <button
                        onClick={onEdit}
                        className="group relative flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm text-gray-300 transition-all hover:bg-orange-500/20 hover:text-white hover:scale-105 cursor-pointer"
                        title="Éditer la visualisation"
                    >
                        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                        <span className="hidden sm:inline">Éditer</span>
                    </button>

                    {onImportConfig && (
                        <>
                            <button
                                onClick={handleImportClick}
                                className="group relative flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm text-gray-300 transition-all hover:bg-yellow-500/20 hover:text-white hover:scale-105 cursor-pointer"
                                title="Importer Configuration (JSON)"
                            >
                                <Upload className="h-4 w-4" />
                                <span className="hidden sm:inline">Import</span>
                            </button>
                        </>
                    )}
                </>
            )}

            {(onExportReport || onExportJSON || onExportCSVNodes) && (
                <>
                    <div className={dividerClass}></div>
                    <div className="relative" ref={exportRef}>
                        <button
                            onClick={() => setIsExportOpen(!isExportOpen)}
                            className={`group relative flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-all hover:scale-105 cursor-pointer ${isExportOpen
                                ? 'bg-cyan-500/20 text-white'
                                : 'bg-white/5 text-gray-300 hover:bg-cyan-500/20 hover:text-white'
                                }`}
                            title="Options d'export"
                        >
                            <Download className="h-5 w-5" />
                            <span className="hidden sm:inline">Export</span>
                        </button>

                        {isExportOpen && (
                            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 rounded-xl border border-white/10 bg-surface-900/95 p-1 backdrop-blur-xl shadow-2xl animate-in slide-in-from-bottom-2 fade-in duration-200">
                                <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-surface-400">
                                    Exporter Données
                                </div>
                                {onExportReport && (
                                    <button
                                        onClick={() => { onExportReport(); setIsExportOpen(false); }}
                                        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-white/10 hover:text-white transition-colors"
                                    >
                                        <FileText className="h-4 w-4 text-blue-400" />
                                        Rapport (Markdown)
                                    </button>
                                )}
                                {onExportJSON && (
                                    <button
                                        onClick={() => { onExportJSON(); setIsExportOpen(false); }}
                                        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-white/10 hover:text-white transition-colors"
                                    >
                                        <FileJson className="h-4 w-4 text-yellow-400" />
                                        Complet (JSON + Config)
                                    </button>
                                )}
                                {(onExportCSVNodes || onExportCSVEdges) && (
                                    <>
                                        <div className="my-1 h-px bg-white/10" />
                                        {onExportCSVNodes && (
                                            <button
                                                onClick={() => { onExportCSVNodes(); setIsExportOpen(false); }}
                                                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-white/10 hover:text-white transition-colors"
                                            >
                                                <Table className="h-4 w-4 text-green-400" />
                                                Nœuds (CSV)
                                            </button>
                                        )}
                                        {onExportCSVEdges && (
                                            <button
                                                onClick={() => { onExportCSVEdges(); setIsExportOpen(false); }}
                                                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-white/10 hover:text-white transition-colors"
                                            >
                                                <Table className="h-4 w-4 text-purple-400" />
                                                Liens (CSV)
                                            </button>
                                        )}
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                </>
            )}

            {!hideShare && onShare && (
                <>
                    <div className={dividerClass}></div>
                    <button
                        onClick={onShare}
                        className="group relative flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm text-gray-300 transition-all hover:bg-green-500/20 hover:text-white hover:scale-105 cursor-pointer"
                        title="Partager"
                    >
                        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                        </svg>
                        <span className="hidden sm:inline">Partager</span>
                    </button>
                </>
            )}
        </div>
    );
}
