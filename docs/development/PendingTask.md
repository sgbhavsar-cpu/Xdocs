Books
- Left side menu should be sizable
- Croll bar should be slim
- when page is published and user click on save draft, it should show two pages in list, one publised and other is draft version. When we click on publish on draft page, it will be repalced original pusblished one.

In mark down editor
- Image resizing and positioning if possible.
- Code segment should have drop down to select language which is supported.

As html control, we should have configuration block so if customer passes request variable "ISDEV=1" then it should render configuration as bellow
- Configuration of space and book to show in runtime.
- Any CSS override if required to match control with site level colors and theme.
- Use globle variables for light and dark theme.

For deployment in other platform
- Deployment package with postgresql script to create required table. All tables should be prefix with "Docs_". It should have script to deploy or configure other things like redis, minio and scipt to host api in that server.


