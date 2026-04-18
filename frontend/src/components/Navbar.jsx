import { NavLink } from "react-router-dom";

const Navbar = () => {
  return (
    <nav className="bg-gray-950 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
      
      {/* Logo */}
      <div className="text-white font-bold text-xl tracking-wide">
        💧 NRW <span className="text-blue-400">Monitor</span>
      </div>

      {/* Nav Links */}
      <div className="flex gap-6">
        <NavLink
          to="/"
          className={({ isActive }) =>
            isActive
              ? "text-blue-400 font-semibold border-b-2 border-blue-400 pb-1"
              : "text-gray-400 hover:text-white transition"
          }
        >
          Dashboard
        </NavLink>

        <NavLink
          to="/monitor"
          className={({ isActive }) =>
            isActive
              ? "text-blue-400 font-semibold border-b-2 border-blue-400 pb-1"
              : "text-gray-400 hover:text-white transition"
          }
        >
          Live Monitor
        </NavLink>

        <NavLink
          to="/map"
          className={({ isActive }) =>
            isActive
              ? "text-blue-400 font-semibold border-b-2 border-blue-400 pb-1"
              : "text-gray-400 hover:text-white transition"
          }
        >
          Map View
        </NavLink>

        <NavLink
          to="/alerts"
          className={({ isActive }) =>
            isActive
              ? "text-blue-400 font-semibold border-b-2 border-blue-400 pb-1"
              : "text-gray-400 hover:text-white transition"
          }
        >
          Alerts & Reports
        </NavLink>
      </div>
    </nav>
  );
};

export default Navbar;