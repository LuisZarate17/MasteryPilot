# Rebuilding the site's CSS

`static/css/app.css` is prebuilt with Tailwind CSS 3.4.17 from the classes used
in `tutor/templates/`. It is committed, so running the site needs no Node.js and
no network access. Rebuild it only after changing classes in a template.

From this folder (`code/llmsite/tailwind/`), with Node.js installed:

```
npx tailwindcss@3.4.17 -c tailwind.config.js -i input.css -o ../static/css/app.css --minify
```

Tailwind finds classes by scanning the templates as text. A class name built at
runtime in JavaScript, such as `"text-" + colour`, is invisible to it and will
be missing from the CSS. Write class names out in full.

The brand colours that used to be configured inline in `base.html` now live in
`tailwind.config.js`.
