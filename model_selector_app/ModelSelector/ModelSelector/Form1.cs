using ModelSelector.Backend;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;

namespace ModelSelector
{
    public partial class Form1 : Form
    {
        bool debug = false;

        public ScrapeHuggingfaceData scraper;

        ListViewItem selectedItem;

        string envFilePath = "";

        bool envLoaded = false;

        public Form1()
        {
            InitializeComponent();
        }

        private void Form1_Load(object sender, EventArgs e)
        {
            if (debug)
            {
                AllocConsole();
            }
            LoadingForm loadForm = new LoadingForm();
            loadForm.Show();
            this.scraper = new ScrapeHuggingfaceData();
            this.EnvFileLoadedToggle(false);
            this.LoadScrapedData();

            loadForm.Hide();
        }

        private void modelListView_SelectedIndexChanged(object sender, EventArgs e)
        {
            if (modelListView.SelectedItems.Count > 0)
            {
                selectedItem = ((ListView)sender).SelectedItems[0];
                this.selectedLabel.Text = "Currently Selected Model: " + selectedItem.Text;

                if (envLoaded)
                {
                    this.applyButton.Enabled = true;
                }
            }
        }

        private void LoadScrapedData()
        {
            List<Model> models = this.scraper.Scrape(4);

            this.modelListView.Items.Clear();
            Console.WriteLine("Models List:");
            foreach (Model model in models)
            {
                Console.WriteLine(model.ModelName + ", " + model.Parameters + ", " + model.LastUpdated + ", " + model.Downloads);

                ListViewItem item = new ListViewItem(model.ModelName);

                item.SubItems.Add(model.Parameters);
                item.SubItems.Add(model.LastUpdated);
                item.SubItems.Add(model.Downloads);

                this.modelListView.Items.Add(item);
            }
        }

        private void refreshButton_Click(object sender, EventArgs e)
        {
            this.refreshButton.Enabled = false;
            LoadingForm loadForm = new LoadingForm();
            loadForm.Show();
            this.LoadScrapedData();
            loadForm.Hide();
        }

        private void selectenvFileToolStripMenuItem_Click(object sender, EventArgs e)
        {
            OpenFileDialog openDialog = new OpenFileDialog();

            DialogResult result = openDialog.ShowDialog();
            if (result == DialogResult.OK)
            {
                this.envFilePath = openDialog.FileName;
                this.EnvFileLoadedToggle(true);
                this.applyButton.Enabled = true;
            }
        }

        private void EnvFileLoadedToggle(bool loaded)
        {
            if (!loaded)
            {
                this.currentlyLoadedModel.ForeColor = Color.Red;
                this.currentlyLoadedModel.Text = "No .env file loaded - File -> Load .env File";
            }
            else
            {
                this.currentlyLoadedModel.ForeColor = Color.Black;
                string[] lines = File.ReadAllLines(this.envFilePath);

                if (lines.Length != 0)
                {
                    string targetLine = lines.FirstOrDefault(l => l.TrimStart().StartsWith("LANGUAGE_MODEL_ID="));

                    string pattern = "LANGUAGE_MODEL_ID=\"([^\"]+)\"";
                    var match = Regex.Match(targetLine, pattern);

                    this.currentlyLoadedModel.Text = "Currently Loaded Model: " + match.Groups[1].Value;
                }
                else
                {
                    this.currentlyLoadedModel.Text = "Currently Loaded Model: None";
                }
            }
        }

        private void applyButton_Click(object sender, EventArgs e)
        {
            this.currentlyLoadedModel.Text = "Currently Loaded Model: " + this.modelListView.SelectedItems[0].Text;
            this.applyButton.Enabled = false;

            File.WriteAllText(this.envFilePath, "LANGUAGE_MODEL_ID=\"" + this.modelListView.SelectedItems[0].Text + "\"");
        }


        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool AllocConsole();
    }
}
