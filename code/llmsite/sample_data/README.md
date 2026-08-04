# Sample data

Fictional examples showing the file formats the management commands expect.
Every name, school, and email address here is made up (`example.invalid` is a
reserved domain that can never resolve), and the passwords are placeholders
that Django's password validators will reject on purpose.

`students.sample.csv` is the input format for:

```
python manage.py import_students sample_data/students.sample.csv
```

Columns: `username`, `password`, `full_name`, `email`, `school`, `grade`,
`classes` (comma-separated, so quote the field).

**Never commit a real roster.** Student names, schools, and passwords are
personal data — keep the real CSV outside the repository, import it, then
delete it. Passwords are transmitted in plaintext in this file, so treat it as
a credential while it exists and have students change theirs on first login.
