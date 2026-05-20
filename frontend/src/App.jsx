import React, { useState, useEffect } from 'react';
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
  // 从localStorage恢复上次访问的页面
  const [tab, setTab] = useState(() => {
    try {
      const saved = localStorage.getItem('app_current_tab');
      const validTabs = ['projects', 'folders', 'memory', 'chat', 'results', 'casegen', 'conflicts', 'settings'];
      if (saved && validTabs.includes(saved)) {
        return saved;
      }
    } catch (e) {
      console.error('[App] Failed to restore tab:', e);
    }
    return 'projects'; // 默认首页
  });

  // 获取当前项目（从localStorage读取）
  const [currentProject, setCurrentProject] = useState(() => {
    try {
      return localStorage.getItem('casemind.project') || '';
    } catch (e) {
      return '';
    }
  });

  // 监听项目变化
  useEffect(() => {
    const handleStorageChange = () => {
      try {
        setCurrentProject(localStorage.getItem('casemind.project') || '');
      } catch (e) {
        // ignore
      }
    };
    
    window.addEventListener('casemind:project', handleStorageChange);
    // 定期检查项目是否变化
    const interval = setInterval(handleStorageChange, 1000);
    
    return () => {
      window.removeEventListener('casemind:project', handleStorageChange);
      clearInterval(interval);
    };
  }, []);

  // 保存当前页面到localStorage
  useEffect(() => {
    try {
      localStorage.setItem('app_current_tab', tab);
    } catch (e) {
      console.error('[App] Failed to save tab:', e);
    }
  }, [tab]);

  return (
    <div className="app">
      <Sidebar tab={tab} setTab={setTab} />
      <main>
        {tab === 'projects' && <Projects />}
        {tab === 'folders'  && <Folders />}
        {tab === 'memory'   && <Memory />}
        {tab === 'chat'     && <Chat />}
        {tab === 'results'  && <Results />}
        {tab === 'casegen'   && <CaseGen />}
        {tab === 'conflicts' && <Conflicts />}
        {tab === 'settings'  && <Settings />}
      </main>
      {/* 全局进度浮窗 */}
      {currentProject && <GlobalProgress project={currentProject} />}
    </div>
  );
}
