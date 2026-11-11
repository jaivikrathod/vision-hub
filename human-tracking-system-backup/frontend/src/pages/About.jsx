import { Cpu, ScanSearch, ShieldCheck, TriangleAlert } from 'lucide-react'
import { PageHeader } from '../components/ui.jsx'

const ITEMS = [
  { icon: ScanSearch, title: 'Detection & tracking', text: 'Ultralytics YOLO11 detects people (COCO class 0) in each frame and ByteTrack links detections across frames, giving every person a tracking ID drawn above a green bounding box.' },
  { icon: ShieldCheck, title: 'Private by design', text: 'Videos, results and models stay on this computer. No cloud services or external AI APIs are used, and no facial recognition is performed.' },
  { icon: Cpu, title: 'Runs on normal laptops', text: 'Uses an NVIDIA GPU automatically when available and falls back to CPU. Frame skipping and the lightweight YOLO11n model keep CPU processing practical.' },
  { icon: TriangleAlert, title: 'About tracking IDs', text: 'IDs are video-local identifiers produced by ByteTrack. They survive short detection gaps and crossings, but a person may receive a new ID after a long occlusion or when leaving and re-entering the frame. IDs are not identities and are not shared across videos.' },
]

export default function About() {
  return (
    <>
      <PageHeader title="About" subtitle="Local AI-powered human detection & multi-person tracking — version 1" />
      <div className="grid gap-4 md:grid-cols-2">
        {ITEMS.map(({ icon: Icon, title, text }) => (
          <div key={title} className="card p-5">
            <Icon className="h-5 w-5 text-brand-600 dark:text-brand-400" />
            <h2 className="mt-3 font-medium">{title}</h2>
            <p className="mt-1 text-sm muted">{text}</p>
          </div>
        ))}
      </div>
      <div className="card mt-6 p-5 text-sm">
        <h2 className="font-medium">Roadmap</h2>
        <p className="mt-1 muted">
          Every detection box is stored per frame, so future versions can add activity recognition, trajectories,
          entry/exit counting, heatmaps, segmentation outlines and pose estimation without reprocessing videos.
        </p>
      </div>
    </>
  )
}
