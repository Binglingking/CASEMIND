import React, { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar.jsx';
import Projects from './pages/Projects.jsx';
import Folders from './pages/Folders.jsx';
import Memory from './pages/Memory.jsx';
import Chat from './pages/Chat.jsx';
import Results from './pages/Results.jsx';
import CaseGen from './pages/CaseGen.jsx';
import Conflicts from './pages/Conflicts.jsx';
import Settings from './pages/Settings.jsx';
import GlobalProgress from './components/GlobalProgress.jsx';

export default function App() {
  const [currentProject, setCurrentProject] = useState(() => {
    try { return localStorage.getItem('casemind.project') || ''; }
    catch { return ''; }
  });

  useEffect(() => {
    const handleStorageChange = () => {
      try { setCurrentProject(localStorage.getItem('casemind.project') || ''); }
      catch { /* ignore */ }
    };
    window.addEventListener('casemind:project', handleStorageChange);
    window.addEventListener('storage', handleStorageChange);
    return () => {
      window.removeEventListener('casemind:project', handleStorageChange);
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  return (
    <div className="app">
      <Sidebar />
      <main>
        <Routes>
          <Route path="/projects" element={<Projects />} />
          <Route path="/folders" element={<Folders />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/results" element={<Results />} />
          <Route path="/casegen" element={<CaseGen />} />
          <Route path="/conflicts" element={<Conflicts />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Routes>
      </main>
      {currentProject && <GlobalProgress project={currentProject} />}
    </div>
  );
}
