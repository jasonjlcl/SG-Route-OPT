export const tokens = {
  color: {
    primary: "hsl(149 74% 35%)",
    success: "hsl(145 63% 42%)",
    warning: "hsl(36 92% 46%)",
    danger: "hsl(5 78% 46%)",
    surface: "hsl(0 0% 100%)",
    surfaceMuted: "hsl(214 25% 94%)",
  },
  radius: {
    md: 10,
    lg: 12,
    xl: 16,
  },
  shadow: {
    soft: "0 10px 30px rgba(15, 23, 42, 0.08)",
    medium: "0 16px 38px rgba(15, 23, 42, 0.14)",
  },
  spacingScale: [4, 8, 12, 16, 20, 24, 32],
};

export type AppTokens = typeof tokens;
