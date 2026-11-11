import { useState } from 'react'
import { CircleAlert } from 'lucide-react'

export default function VideoPlayer({ src, title, downloadHref }) {
  const [failed, setFailed] = useState(false)
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5 text-sm font-medium dark:border-slate-800">
        {title}
      </div>
      <div className="relative aspect-video bg-black">
        {failed ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center text-sm text-slate-300">
            <CircleAlert className="h-6 w-6" />
            This format can’t be previewed in the browser.
            {downloadHref && <a className="underline" href={downloadHref}>Download the file instead</a>}
          </div>
        ) : (
          <video
            key={src} src={src} controls preload="metadata" playsInline
            className="h-full w-full" onError={() => setFailed(true)}
          />
        )}
      </div>
    </div>
  )
}
