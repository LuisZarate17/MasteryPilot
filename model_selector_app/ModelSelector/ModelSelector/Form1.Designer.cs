namespace ModelSelector
{
    partial class Form1
    {
        /// <summary>
        ///  Required designer variable.
        /// </summary>
        private System.ComponentModel.IContainer components = null;

        /// <summary>
        ///  Clean up any resources being used.
        /// </summary>
        /// <param name="disposing">true if managed resources should be disposed; otherwise, false.</param>
        protected override void Dispose(bool disposing)
        {
            if (disposing && (components != null))
            {
                components.Dispose();
            }
            base.Dispose(disposing);
        }

        #region Windows Form Designer generated code

        /// <summary>
        ///  Required method for Designer support - do not modify
        ///  the contents of this method with the code editor.
        /// </summary>
        private void InitializeComponent()
        {
            ListViewItem listViewItem1 = new ListViewItem("a,a,a,a");
            ListViewItem listViewItem2 = new ListViewItem("");
            ListViewItem listViewItem3 = new ListViewItem("");
            ListViewItem listViewItem4 = new ListViewItem("");
            ListViewItem listViewItem5 = new ListViewItem("");
            ListViewItem listViewItem6 = new ListViewItem("");
            ListViewItem listViewItem7 = new ListViewItem("");
            ListViewItem listViewItem8 = new ListViewItem("");
            ListViewItem listViewItem9 = new ListViewItem("");
            ListViewItem listViewItem10 = new ListViewItem("");
            ListViewItem listViewItem11 = new ListViewItem("");
            ListViewItem listViewItem12 = new ListViewItem("");
            ListViewItem listViewItem13 = new ListViewItem("");
            ListViewItem listViewItem14 = new ListViewItem("");
            ListViewItem listViewItem15 = new ListViewItem("a");
            modelListView = new ListView();
            Model = new ColumnHeader();
            Parameters = new ColumnHeader();
            LastUpdated = new ColumnHeader();
            Downloads = new ColumnHeader();
            currentlyLoadedModel = new Label();
            menuStrip1 = new MenuStrip();
            fileToolStripMenuItem = new ToolStripMenuItem();
            selectenvFileToolStripMenuItem = new ToolStripMenuItem();
            refreshButton = new Button();
            applyButton = new Button();
            selectedLabel = new Label();
            menuStrip1.SuspendLayout();
            SuspendLayout();
            // 
            // modelListView
            // 
            modelListView.Columns.AddRange(new ColumnHeader[] { Model, Parameters, LastUpdated, Downloads });
            modelListView.Items.AddRange(new ListViewItem[] { listViewItem1, listViewItem2, listViewItem3, listViewItem4, listViewItem5, listViewItem6, listViewItem7, listViewItem8, listViewItem9, listViewItem10, listViewItem11, listViewItem12, listViewItem13, listViewItem14, listViewItem15 });
            modelListView.Location = new Point(12, 62);
            modelListView.MultiSelect = false;
            modelListView.Name = "modelListView";
            modelListView.Size = new Size(776, 340);
            modelListView.TabIndex = 0;
            modelListView.UseCompatibleStateImageBehavior = false;
            modelListView.View = View.Details;
            modelListView.SelectedIndexChanged += modelListView_SelectedIndexChanged;
            // 
            // Model
            // 
            Model.Text = "Model";
            Model.Width = 300;
            // 
            // Parameters
            // 
            Parameters.Text = "Parameters";
            Parameters.Width = 150;
            // 
            // LastUpdated
            // 
            LastUpdated.Text = "Last Updated";
            LastUpdated.Width = 150;
            // 
            // Downloads
            // 
            Downloads.Text = "Downloads";
            Downloads.Width = 150;
            // 
            // currentlyLoadedModel
            // 
            currentlyLoadedModel.AutoSize = true;
            currentlyLoadedModel.Location = new Point(12, 34);
            currentlyLoadedModel.Name = "currentlyLoadedModel";
            currentlyLoadedModel.Size = new Size(275, 15);
            currentlyLoadedModel.TabIndex = 1;
            currentlyLoadedModel.Text = "Currently Loaded Model: llama/LLaMA-2B-Instruct";
            // 
            // menuStrip1
            // 
            menuStrip1.Items.AddRange(new ToolStripItem[] { fileToolStripMenuItem });
            menuStrip1.Location = new Point(0, 0);
            menuStrip1.Name = "menuStrip1";
            menuStrip1.Size = new Size(800, 24);
            menuStrip1.TabIndex = 2;
            menuStrip1.Text = "menuStrip1";
            // 
            // fileToolStripMenuItem
            // 
            fileToolStripMenuItem.DropDownItems.AddRange(new ToolStripItem[] { selectenvFileToolStripMenuItem });
            fileToolStripMenuItem.Name = "fileToolStripMenuItem";
            fileToolStripMenuItem.Size = new Size(37, 20);
            fileToolStripMenuItem.Text = "File";
            // 
            // selectenvFileToolStripMenuItem
            // 
            selectenvFileToolStripMenuItem.Name = "selectenvFileToolStripMenuItem";
            selectenvFileToolStripMenuItem.Size = new Size(160, 22);
            selectenvFileToolStripMenuItem.Text = "Select .env File...";
            selectenvFileToolStripMenuItem.Click += selectenvFileToolStripMenuItem_Click;
            // 
            // refreshButton
            // 
            refreshButton.Location = new Point(12, 408);
            refreshButton.Name = "refreshButton";
            refreshButton.Size = new Size(103, 30);
            refreshButton.TabIndex = 3;
            refreshButton.Text = "Refresh";
            refreshButton.UseVisualStyleBackColor = true;
            refreshButton.Click += refreshButton_Click;
            // 
            // applyButton
            // 
            applyButton.Enabled = false;
            applyButton.Location = new Point(590, 408);
            applyButton.Name = "applyButton";
            applyButton.Size = new Size(198, 30);
            applyButton.TabIndex = 4;
            applyButton.Text = "Apply Selected Model";
            applyButton.UseVisualStyleBackColor = true;
            applyButton.Click += applyButton_Click;
            // 
            // selectedLabel
            // 
            selectedLabel.AutoSize = true;
            selectedLabel.Location = new Point(397, 34);
            selectedLabel.Name = "selectedLabel";
            selectedLabel.Size = new Size(143, 15);
            selectedLabel.TabIndex = 5;
            selectedLabel.Text = "Currently Selected Model:";
            // 
            // Form1
            // 
            AutoScaleDimensions = new SizeF(7F, 15F);
            AutoScaleMode = AutoScaleMode.Font;
            ClientSize = new Size(800, 450);
            Controls.Add(selectedLabel);
            Controls.Add(applyButton);
            Controls.Add(refreshButton);
            Controls.Add(currentlyLoadedModel);
            Controls.Add(modelListView);
            Controls.Add(menuStrip1);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MainMenuStrip = menuStrip1;
            MaximizeBox = false;
            Name = "Form1";
            ShowIcon = false;
            StartPosition = FormStartPosition.CenterScreen;
            Text = "Model Swapper";
            Load += Form1_Load;
            menuStrip1.ResumeLayout(false);
            menuStrip1.PerformLayout();
            ResumeLayout(false);
            PerformLayout();
        }

        #endregion

        private ListView modelListView;
        private ColumnHeader Model;
        private ColumnHeader Parameters;
        private ColumnHeader LastUpdated;
        private ColumnHeader Downloads;
        private Label currentlyLoadedModel;
        private MenuStrip menuStrip1;
        private ToolStripMenuItem fileToolStripMenuItem;
        private ToolStripMenuItem selectenvFileToolStripMenuItem;
        private Button refreshButton;
        private Button applyButton;
        private Label selectedLabel;
    }
}
