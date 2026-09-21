import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { AssessmentReport } from './pages/AssessmentReport'
import { Dashboard } from './pages/Dashboard'
import { Exports } from './pages/Exports'
import { GapsPage } from './pages/GapsPage'
import { LineageExplorer } from './pages/LineageExplorer'
import { MeasureInventory } from './pages/MeasureInventory'
import { MetricView } from './pages/MetricView'
import { MigrationPlan } from './pages/MigrationPlan'
import { PowerBIInventory } from './pages/PowerBIInventory'
import { ProjectUpload } from './pages/ProjectUpload'
import { RelationshipInventory } from './pages/RelationshipInventory'
import { SettingsPage } from './pages/SettingsPage'
import { SqlConversion } from './pages/SqlConversion'
import { TeradataAssessment } from './pages/TeradataAssessment'
import { Validation } from './pages/Validation'
import { ProjectProvider } from './state/ProjectContext'
import { ThemeProvider } from './state/ThemeContext'

export default function App() {
  return (
    <ThemeProvider>
      <ProjectProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/upload" element={<ProjectUpload />} />
            <Route path="/powerbi/tables" element={<PowerBIInventory />} />
            <Route path="/powerbi/measures" element={<MeasureInventory />} />
            <Route path="/powerbi/relationships" element={<RelationshipInventory />} />
            <Route path="/teradata" element={<TeradataAssessment />} />
            <Route path="/lineage" element={<LineageExplorer />} />
            <Route path="/gaps" element={<GapsPage />} />
            <Route path="/databricks" element={<MetricView />} />
            <Route path="/sql-conversion" element={<SqlConversion />} />
            <Route path="/migration-plan" element={<MigrationPlan />} />
            <Route path="/validation" element={<Validation />} />
            <Route path="/report" element={<AssessmentReport />} />
            <Route path="/exports" element={<Exports />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </ProjectProvider>
    </ThemeProvider>
  )
}
