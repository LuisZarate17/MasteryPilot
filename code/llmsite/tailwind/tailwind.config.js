// Builds static/css/app.css from the classes the templates use.
// The site used to run Tailwind's CDN script in every browser, which sent each
// page view to a third party. See README.md in this folder to rebuild.
module.exports = {
  content: ["../tutor/templates/**/*.html"],
  theme: {
    extend: {
      colors: {
        brand: { 500: "#5b6df2", 600: "#3f51d7", 700: "#2f3dad" },
      },
    },
  },
  plugins: [],
};
