import { Routes, Route, NavLink, Navigate, Link, useNavigate } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import QuestionBank from "./pages/QuestionBank";
import CreateExam from "./pages/CreateExam";
import ExamPage from "./pages/ExamPage";
import Results from "./pages/Results";
import Login from "./pages/Login";
import About from "./pages/About";

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/bank", label: "Question Bank" },
  { to: "/create", label: "New Exam" },
];

function Protected({ children }) {
  return localStorage.getItem("token") ? children : <Navigate to="/login" replace />;
}

export default function App() {
  const navigate = useNavigate();
  const loggedIn = !!localStorage.getItem("token");
  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    navigate("/login");
  };
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="bg-indigo-700 text-white shadow">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-8">
          <span className="font-bold text-lg tracking-tight">Quizloom</span>
          <nav className="flex gap-5 text-sm">
            {nav.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  isActive ? "font-semibold underline" : "opacity-80 hover:opacity-100"
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
          {loggedIn && (
            <div className="ml-auto flex items-center gap-3 text-sm">
              <span className="opacity-80">{localStorage.getItem("username")}</span>
              <button onClick={logout} className="underline opacity-80 hover:opacity-100">Logout</button>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/about" element={<About />} />
          <Route path="/" element={<Protected><Dashboard /></Protected>} />
          <Route path="/bank" element={<Protected><QuestionBank /></Protected>} />
          <Route path="/create" element={<Protected><CreateExam /></Protected>} />
          <Route path="/exam/:id" element={<Protected><ExamPage /></Protected>} />
          <Route path="/results/:id" element={<Protected><Results /></Protected>} />
        </Routes>
      </main>

      <footer className="max-w-5xl mx-auto px-4 pb-8 text-[11px] text-gray-500">
        AI-generated questions may be inaccurate. Independent study aid, not affiliated with IAPP or ISC2.{" "}
        <Link to="/about" className="underline">Privacy &amp; disclaimer</Link>
      </footer>
    </div>
  );
}
