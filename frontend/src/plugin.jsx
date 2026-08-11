import React from 'react';
import ReactDOM from 'react-dom/client';
import FloatingWidget from './components/FloatingWidget';
import './index.css';

// Standalone self-initializing plugin launcher
window.initSbiCmsWidget = function (options = {}) {
  const containerId = options.containerId || 'sbi-cms-widget-root';
  let container = document.getElementById(containerId);

  if (!container) {
    container = document.createElement('div');
    container.id = containerId;
    document.body.appendChild(container);
  }

  const root = ReactDOM.createRoot(container);
  root.render(
    <React.StrictMode>
      <FloatingWidget
        gatewayUrl={options.gatewayUrl || ''}
        initialOpen={options.initialOpen || false}
      />
    </React.StrictMode>
  );

  return root;
};

// Auto-initialize if data-auto-init attribute is present on the script tag
document.addEventListener('DOMContentLoaded', () => {
  const currentScript = document.currentScript || document.querySelector('script[data-sbi-cms-gateway]');
  if (currentScript) {
    const gatewayUrl = currentScript.getAttribute('data-sbi-cms-gateway') || '';
    const autoOpen = currentScript.getAttribute('data-auto-open') === 'true';
    window.initSbiCmsWidget({
      gatewayUrl: gatewayUrl,
      initialOpen: autoOpen
    });
  }
});
