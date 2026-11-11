import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { SUPPORTED_EXTENSIONS } from '../utils/format.js'

export default function Dropzone({ onFile, disabled }) {
  const inputRef = useRef(null)
  const [over, setOver] = useState(false)

  const pick = (files) => {
    if (!disabled && files && files[0]) onFile(files[0])
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files) }}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click() }}
      role="button" tabIndex={0}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition ${
        over ? 'border-brand-500 bg-brand-50 dark:bg-brand-500/10'
          : 'border-slate-300 hover:border-brand-400 dark:border-slate-700'
      } ${disabled ? 'pointer-events-none opacity-60' : ''}`}
    >
      <div className="rounded-full bg-brand-50 p-3 text-brand-600 dark:bg-brand-500/10 dark:text-brand-400">
        <Upload className="h-6 w-6" />
      </div>
      <p className="mt-3 font-medium">Drag and drop a video here</p>
      <p className="mt-1 text-sm muted">
        {SUPPORTED_EXTENSIONS.map((e) => e.slice(1).toUpperCase()).join(', ')} supported
      </p>
      <button type="button" className="btn-secondary mt-4" onClick={(e) => { e.stopPropagation(); inputRef.current?.click() }}>
        Browse files
      </button>
      <input
        ref={inputRef} type="file" className="hidden"
        accept={[...SUPPORTED_EXTENSIONS, 'video/*'].join(',')}
        onChange={(e) => { pick(e.target.files); e.target.value = '' }}
      />
    </div>
  )
}
