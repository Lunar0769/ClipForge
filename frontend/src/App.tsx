import { AnimatePresence } from "motion/react";
import { Route, Routes, useLocation } from "react-router";
import { AppShell } from "./components/AppShell";
import { NotFound } from "./components/NotFound";
import HomePage from "./features/home/HomePage";
import ProcessingPage from "./features/processing/ProcessingPage";

export default function App() {
  const location = useLocation();
  return (
    <AppShell>
      <AnimatePresence mode="wait">
        <Routes location={location} key={location.pathname}>
          <Route path="/" element={<HomePage />} />
          <Route path="/projects/:projectId" element={<ProcessingPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AnimatePresence>
    </AppShell>
  );
}
