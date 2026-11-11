import { Route, Routes } from 'react-router-dom'
import MainLayout from './layouts/MainLayout.jsx'
import Dashboard from './pages/Dashboard.jsx'
import UploadVideo from './pages/UploadVideo.jsx'
import VideoLibrary from './pages/VideoLibrary.jsx'
import ModelLibrary from './pages/ModelLibrary.jsx'
import ModelDetails from './pages/ModelDetails.jsx'
import ConfigureAnalysis from './pages/ConfigureAnalysis.jsx'
import AnalysisJobs from './pages/AnalysisJobs.jsx'
import AnalysisProcessing from './pages/AnalysisProcessing.jsx'
import AnalysisResults from './pages/AnalysisResults.jsx'
import Settings from './pages/Settings.jsx'
import About from './pages/About.jsx'
import NotFound from './pages/NotFound.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<MainLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="upload" element={<UploadVideo />} />
        <Route path="videos" element={<VideoLibrary />} />
        <Route path="models" element={<ModelLibrary />} />
        <Route path="models/:modelId" element={<ModelDetails />} />
        <Route path="analyze" element={<ConfigureAnalysis />} />
        <Route path="jobs" element={<AnalysisJobs />} />
        <Route path="jobs/:jobId" element={<AnalysisProcessing />} />
        <Route path="jobs/:jobId/results" element={<AnalysisResults />} />
        <Route path="settings" element={<Settings />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
