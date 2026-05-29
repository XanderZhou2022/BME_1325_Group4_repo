import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./dashboard/styles.css";
import "./viewer/viewer.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
