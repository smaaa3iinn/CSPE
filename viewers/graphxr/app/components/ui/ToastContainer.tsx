'use client';

import { useToastStore, ToastType } from '@/app/store/useToastStore';

/**
 * Composant pour afficher les notifications Toast.
 * Doit être placé dans le layout racine.
 */
export default function ToastContainer() {
    const { toasts, removeToast } = useToastStore();

    return (
        <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
            {toasts.map((toast) => (
                <div
                    key={toast.id}
                    className={`
            min-w-[300px] rounded-lg p-4 shadow-lg transition-all duration-300 animate-in slide-in-from-right-full
            ${getToastStyles(toast.type)}
          `}
                    role="alert"
                >
                    <div className="flex items-center justify-between">
                        <p className="text-sm font-medium">{toast.message}</p>
                        <button
                            onClick={() => removeToast(toast.id)}
                            className="ml-4 text-current opacity-70 hover:opacity-100"
                        >
                            ✕
                        </button>
                    </div>
                </div>
            ))}
        </div>
    );
}

function getToastStyles(type: ToastType): string {
    switch (type) {
        case 'success':
            return 'bg-green-500/90 backdrop-blur-md border border-green-400/30 text-white shadow-lg shadow-green-500/20';
        case 'error':
            return 'bg-red-500/90 backdrop-blur-md border border-red-400/30 text-white shadow-lg shadow-red-500/20';
        case 'warning':
            return 'bg-yellow-500/90 backdrop-blur-md border border-yellow-400/30 text-white shadow-lg shadow-yellow-500/20';
        case 'info':
            return 'bg-blue-500/90 backdrop-blur-md border border-blue-400/30 text-white shadow-lg shadow-blue-500/20';
        default:
            return 'bg-surface-800/90 backdrop-blur-md border border-surface-700/30 text-white shadow-lg';
    }
}
