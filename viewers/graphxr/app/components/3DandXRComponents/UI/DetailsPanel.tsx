'use client';

interface DetailsPanelProps {
    data: any;
    type: 'node' | 'edge' | null;
    onClose: () => void;
    height?: string;
}

export default function DetailsPanel({ data, type, onClose, height }: DetailsPanelProps) {
    if (!data || !type) return null;

    return (
        <div
            className="fixed z-50 w-80 flex flex-col animate-slide-up rounded-xl border border-surface-50/10 bg-surface-950/95 backdrop-blur-xl shadow-2xl"
            style={{
                right: '2rem',
                bottom: '6rem',
                left: 'auto',
                top: 'auto',
                maxHeight: height || '60vh'
            }}
        >
            <div className="flex items-center justify-between p-4 border-b border-surface-50/10 bg-surface-950/95 rounded-t-xl shrink-0">
                <h3 className={`text-lg font-bold ${type === 'node' ? 'text-blue-400' : 'text-purple-400'}`}>
                    {type === 'node' ? 'Détails du Nœud' : 'Détails du Lien'}
                </h3>
                <button
                    onClick={onClose}
                    className="rounded-full p-1 text-surface-400 hover:bg-surface-50/10 hover:text-surface-50 cursor-pointer transition-colors"
                >
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>

            <div className="overflow-y-auto p-4 space-y-4 custom-scrollbar">
                {type === 'node' ? (
                    // Node specific view
                    <>
                        <div className="bg-blue-500/10 rounded-lg p-3 border border-blue-500/20">
                            <p className="text-xs text-blue-400 font-semibold mb-1">Identifiant</p>
                            <p className="font-mono text-surface-50 break-words text-lg">{data.id || 'N/A'}</p>
                        </div>

                        {data.label && (
                            <div>
                                <p className="text-sm text-surface-400">Label</p>
                                <p className="text-surface-50 font-medium">{data.label}</p>
                            </div>
                        )}
                    </>
                ) : (
                    // Edge specific view
                    <div className="grid grid-cols-2 gap-3">
                        <div className="rounded-lg bg-gradient-to-br from-purple-500/10 to-purple-600/5 border border-purple-500/20 p-3">
                            <p className="text-xs text-purple-400 font-semibold mb-1">Source</p>
                            <p className="text-sm text-surface-50 font-mono break-words">{data.source}</p>
                        </div>
                        <div className="rounded-lg bg-gradient-to-br from-pink-500/10 to-pink-600/5 border border-pink-500/20 p-3">
                            <p className="text-xs text-pink-400 font-semibold mb-1">Cible</p>
                            <p className="text-sm text-surface-50 font-mono break-words">{data.target}</p>
                        </div>
                    </div>
                )}

                <div className="space-y-3 pt-2">
                    <p className="text-sm font-semibold text-surface-300 border-b border-surface-50/10 pb-1">
                        Propriétés {type === 'node' ? 'du Nœud' : 'du Lien'}
                    </p>
                    {Object.entries(data).map(([key, value]) => {
                        if (['id', 'x', 'y', 'z', 'source', 'target', 'label'].includes(key)) return null;

                        // Try to parse JSON strings
                        let parsedValue = value;
                        if (typeof value === 'string' && (value.trim().startsWith('{') || value.trim().startsWith('['))) {
                            try {
                                parsedValue = JSON.parse(value);
                            } catch (e) {
                                parsedValue = value;
                            }
                        }

                        // Handle nested objects
                        if (typeof parsedValue === 'object' && parsedValue !== null && !Array.isArray(parsedValue)) {
                            return (
                                <div key={key} className="space-y-2">
                                    <p className={`text-xs font-bold uppercase tracking-wider flex items-center gap-2 ${type === 'node' ? 'text-blue-400' : 'text-purple-400'}`}>
                                        <span className={`inline-block w-1 h-4 rounded ${type === 'node' ? 'bg-blue-400' : 'bg-purple-400'}`}></span>
                                        {key}
                                    </p>
                                    <div className={`ml-3 space-y-2 border-l-2 pl-3 ${type === 'node' ? 'border-blue-500/30' : 'border-purple-500/30'}`}>
                                        {Object.entries(parsedValue).map(([nestedKey, nestedValue]) => (
                                            <div key={`${key}.${nestedKey}`} className="flex flex-col gap-1 text-sm">
                                                <span className="text-surface-400 text-xs">{nestedKey}</span>
                                                <span className="text-surface-50 font-medium break-words whitespace-pre-wrap bg-surface-50/5 p-1.5 rounded text-xs font-mono max-h-24 overflow-y-auto custom-scrollbar">
                                                    {typeof nestedValue === 'object'
                                                        ? JSON.stringify(nestedValue, null, 2)
                                                        : String(nestedValue)}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            );
                        }

                        // Handle arrays
                        if (Array.isArray(parsedValue)) {
                            return (
                                <div key={key} className="space-y-2">
                                    <p className={`text-xs font-bold uppercase tracking-wider flex items-center gap-2 ${type === 'node' ? 'text-green-400' : 'text-pink-400'}`}>
                                        <span className={`inline-block w-1 h-4 rounded ${type === 'node' ? 'bg-green-400' : 'bg-pink-400'}`}></span>
                                        {key}
                                    </p>
                                    <div className="ml-3 space-y-1">
                                        {parsedValue.map((item, idx) => (
                                            <div key={`${key}.${idx}`} className="text-sm text-surface-300 break-words whitespace-pre-wrap bg-surface-50/5 p-1.5 rounded mb-1 font-mono text-xs">
                                                • {typeof item === 'object' ? JSON.stringify(item) : String(item)}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            );
                        }

                        // Simple values
                        const displayValue = (parsedValue === null || parsedValue === undefined) ? 'N/A' : String(parsedValue);

                        return (
                            <div key={key} className="flex flex-col gap-1 py-2 border-b border-surface-50/5 text-sm">
                                <span className="text-surface-400 font-medium text-xs uppercase tracking-wider">{key}</span>
                                <span className="text-surface-50 break-words whitespace-pre-wrap bg-surface-50/5 p-2 rounded-md text-xs font-mono max-h-32 overflow-y-auto custom-scrollbar" title={displayValue}>
                                    {displayValue}
                                </span>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
