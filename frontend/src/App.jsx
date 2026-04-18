import { BrowserRouter, Routes, Route } from "react-router-dom";
import Monitor from "./pages/Monitor";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/monitor" element={<Monitor />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;