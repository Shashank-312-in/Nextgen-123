import { useEffect, useState } from "react";

interface SplashScreenProps {
  onComplete?: () => void;
  message?: string;
  minDisplayTimeMs?: number;
}

export function SplashScreen({
  onComplete,
  message = "Initializing System & Environment...",
  minDisplayTimeMs = 3800, // Displays for 3.5 to 4 seconds as requested
}: SplashScreenProps) {
  const [progress, setProgress] = useState(5);
  const [statusText, setStatusText] = useState(message);
  const [fadeOut, setFadeOut] = useState(false);

  useEffect(() => {
    const statusSteps = [
      { at: 15, text: "Initializing Core Modules..." },
      { at: 35, text: "Connecting to Secure Database..." },
      { at: 60, text: "Verifying Authentication Credentials..." },
      { at: 85, text: "Loading Interactive Dashboards..." },
      { at: 100, text: "System Ready — Welcome!" },
    ];

    const startTime = Date.now();
    // Smooth progress update over ~3.5 seconds
    const interval = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const targetProgress = Math.min(100, Math.floor((elapsed / (minDisplayTimeMs - 400)) * 100));

      setProgress(targetProgress);

      const currentStep = statusSteps.filter((s) => targetProgress >= s.at).pop();
      if (currentStep) {
        setStatusText(currentStep.text);
      }

      if (targetProgress >= 100) {
        clearInterval(interval);
        setTimeout(() => {
          setFadeOut(true);
          setTimeout(() => {
            if (onComplete) onComplete();
          }, 500); // 500ms smooth fade out
        }, 300);
      }
    }, 40);

    return () => clearInterval(interval);
  }, [minDisplayTimeMs, onComplete]);

  return (
    <div className={`splash-container ${fadeOut ? "splash-fade-out" : ""}`}>
      {/* Ambient background glow orbs */}
      <div className="splash-glow splash-glow-1" />
      <div className="splash-glow splash-glow-2" />
      <div className="splash-glow splash-glow-3" />

      {/* Floating particles */}
      <div className="splash-particles">
        <div className="particle particle-1" />
        <div className="particle particle-2" />
        <div className="particle particle-3" />
        <div className="particle particle-4" />
        <div className="particle particle-5" />
      </div>

      {/* Central content */}
      <div className="splash-content">
        {/* Animated logo graphics with dual rotating orbital rings & sonar pulse */}
        <div className="splash-logo-wrapper">
          <div className="splash-sonar-wave" />
          <div className="splash-sonar-wave wave-2" />
          <div className="splash-ring-outer" />
          <div className="splash-ring-inner" />
          <div className="splash-logo-badge">
            <img
              src="/logo.png"
              alt="NextGen SMS Logo"
              style={{ objectFit: "cover", width: "100%", height: "100%", borderRadius: "50%" }}
            />
          </div>
        </div>

        {/* Brand headers with animated gradient shimmer */}
        <h1 className="splash-title">NextGen SMS</h1>
        <p className="splash-subtitle">STUDENT MANAGEMENT SYSTEM</p>
        <p className="splash-tagline">Smart Campus. Smarter Management.</p>

        {/* Progress bar container with loading graphics */}
        <div className="splash-progress-box">
          <div className="splash-progress-bar-bg">
            <div className="splash-progress-fill" style={{ width: `${progress}%` }}>
              <div className="splash-progress-head-glow" />
            </div>
          </div>
          <div className="splash-status-row">
            <span className="splash-status-text">
              <span className="splash-spinner-dots">●</span> {statusText}
            </span>
            <span className="splash-percent-text">{progress}%</span>
          </div>
        </div>

        {/* Security badge */}
        <div className="splash-footer-badge">
          <span className="splash-shield-icon">🛡️</span> Encrypted &amp; Secure Environment
        </div>
      </div>
    </div>
  );
}
