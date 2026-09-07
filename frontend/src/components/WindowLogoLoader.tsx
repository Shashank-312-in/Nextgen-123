import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

export function WindowLogoLoader() {
  const location = useLocation();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Whenever location changes (opening next windows/pages), trigger the animated logo loader
    setLoading(true);
    const timer = setTimeout(() => {
      setLoading(false);
    }, 750); // Smooth 750ms window transition logo loader
    return () => clearTimeout(timer);
  }, [location.pathname, location.search]);

  if (!loading) return null;

  return (
    <div className="window-logo-loader-overlay">
      <div className="window-logo-loader-card">
        <div className="window-logo-spinner-wrapper">
          <div className="window-logo-ring-spin" />
          <div className="window-logo-badge">
            <img
              src="/logo.png"
              alt="NextGen SMS Logo"
              style={{ objectFit: "cover", width: "100%", height: "100%", borderRadius: "50%" }}
            />
          </div>
        </div>
        <div className="window-logo-loader-text">
          <span className="window-loader-pulse-dot" /> NextGen SMS
        </div>
      </div>
    </div>
  );
}
