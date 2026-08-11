import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import { Toaster } from 'react-hot-toast';
import './index.css';
import store from './app/store';
import AppRouter from './routes/AppRouter';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Provider store={store}>
      <Toaster position="top-right" />
      <AppRouter />
    </Provider>
  </StrictMode>,
);
