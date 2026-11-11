import { Link } from 'react-router-dom'
import { EmptyState } from '../components/ui.jsx'
import { TriangleAlert } from 'lucide-react'

export default function NotFound() {
  return (
    <div className="card">
      <EmptyState icon={TriangleAlert} title="Page not found" action={<Link className="btn-primary" to="/">Go to dashboard</Link>}>
        The page you are looking for does not exist.
      </EmptyState>
    </div>
  )
}
