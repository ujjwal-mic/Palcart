// The entry point: it puts our <App /> inside the <div id="root"> of index.html.
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
