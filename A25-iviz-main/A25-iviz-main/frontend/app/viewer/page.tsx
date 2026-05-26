import { Suspense } from 'react';
import ViewerClient from './ViewerClient';

export default function ViewerPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-black text-white">
          Loading CSPE graph viewer...
        </main>
      }
    >
      <ViewerClient />
    </Suspense>
  );
}
