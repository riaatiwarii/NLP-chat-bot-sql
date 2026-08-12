import React from 'react';
import ReactDOM from 'react-dom/client';
import FloatingWidget from './components/FloatingWidget';
import './index.css';

// Standalone self-initializing plugin launcher with Shadow DOM isolation
window.initSbiCmsWidget = function (options = {}) {
  const containerId = options.containerId || 'sbi-cms-widget-root';
  let container = document.getElementById(containerId);

  if (!container) {
    container = document.createElement('div');
    container.id = containerId;
    document.body.appendChild(container);
  }

  // Shadow DOM Encapsulation for 100% Style Isolation
  let renderTarget = container;
  if (options.useShadowDOM !== false && !container.shadowRoot) {
    const shadow = container.attachShadow({ mode: 'open' });

    // Inject stylesheet inside shadow root so styles apply to widget without leaking to host
    const gatewayUrl = (options.gatewayUrl || '').replace(/\/$/, '');
    const cssUrl = gatewayUrl ? `${gatewayUrl}/plugin/widget.css` : '/plugin/widget.css';
    
    const linkEl = document.createElement('link');
    linkEl.rel = 'stylesheet';
    linkEl.href = cssUrl;
    shadow.appendChild(linkEl);

    // Mount point inside shadow DOM
    renderTarget = document.createElement('div');
    renderTarget.className = 'sbi-widget-shadow-mount';
    shadow.appendChild(renderTarget);
  } else if (container.shadowRoot) {
    renderTarget = container.shadowRoot.querySelector('.sbi-widget-shadow-mount') || container.shadowRoot;
  }

  const root = ReactDOM.createRoot(renderTarget);
  root.render(
    <React.StrictMode>
      <FloatingWidget
        gatewayUrl={options.gatewayUrl || ''}
        initialOpen={options.initialOpen || false}
        theme={options.theme || 'dark'}
        position={options.position || 'bottom-right'}
        apiKey={options.apiKey || ''}
      />
    </React.StrictMode>
  );

  return root;
};

// Auto-initialize if script tag with data-sbi-cms-gateway or data-sbi-widget is present
const autoInitWidget = () => {
  const currentScript = document.currentScript || document.querySelector('script[data-sbi-cms-gateway], script[data-sbi-widget]');
  if (currentScript) {
    const gatewayUrl = currentScript.getAttribute('data-sbi-cms-gateway') || currentScript.getAttribute('data-gateway') || '';
    const autoOpen = currentScript.getAttribute('data-auto-open') === 'true';
    const theme = currentScript.getAttribute('data-theme') || 'dark';
    const position = currentScript.getAttribute('data-position') || 'bottom-right';
    const apiKey = currentScript.getAttribute('data-api-key') || '';

    window.initSbiCmsWidget({
      gatewayUrl: gatewayUrl,
      initialOpen: autoOpen,
      theme: theme,
      position: position,
      apiKey: apiKey
    });
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', autoInitWidget);
} else {
  autoInitWidget();
}
