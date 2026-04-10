import React from 'react';
import ReactDOM from 'react-dom/client';
import CesiumViewer from './CesiumViewer';
import ErrorBoundary from './ErrorBoundary';
import './styles.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <ErrorBoundary>
      <CesiumViewer />
    </ErrorBoundary>
  </React.StrictMode>
);