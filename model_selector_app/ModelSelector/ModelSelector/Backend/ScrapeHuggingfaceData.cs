using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;

using HtmlAgilityPack;
using HtmlDocument = HtmlAgilityPack.HtmlDocument;

namespace ModelSelector.Backend
{
    public class ScrapeHuggingfaceData
    {
        HtmlWeb web;

        public ScrapeHuggingfaceData()
        {
            this.web = new HtmlWeb();
        }

        private HtmlDocument LoadHuggingFace(int page)
        {
            if (page == 1)
            {
                return web.Load("https://huggingface.co/models?pipeline_tag=text-generation&sort=trending");
            }
            else
            {
                StringBuilder builder = new StringBuilder();
                builder.Append("https://huggingface.co/models?pipeline_tag=text-generation");

                builder.Append("&p=" + (page - 1).ToString());
                builder.Append("&sort=trending");
                return web.Load(builder.ToString());
            }
        }

        public List<Model> Scrape(int numPages)
        {
            List<Model> modelsList = new List<Model>();

            for (int i = 1; i <= numPages; i++)
            {
                // Load doc and get all model elements
                HtmlDocument doc = this.LoadHuggingFace(i);
                var elements = doc.DocumentNode.QuerySelectorAll("article.overview-card-wrapper");
                Console.WriteLine($"Page {i}: found {elements.Count} article.overview-card-wrapper nodes");


                foreach (HtmlNode element in elements)
                {
                    var nameNode = element.SelectSingleNode(".//h4");
                    var paramNode = element.SelectSingleNode(".//span[contains(@title,'Number of parameters')]");
                    var timeNode = element.SelectSingleNode(".//time");
                    var statsDiv = element.SelectSingleNode(
                        ".//div[contains(@class,'mr-1') and contains(@class,'items-center') and contains(@class,'overflow-hidden')]");

                    if (nameNode == null || paramNode == null || timeNode == null || statsDiv == null)
                    {
                        Console.WriteLine("Skipped one element. name={0}, param={1}, time={2}, stats={3}", nameNode != null, paramNode != null, timeNode != null, statsDiv != null);
                        continue;
                    }

                    string name = nameNode.InnerText.Trim();
                    string parameters = paramNode.InnerText.Trim();
                    string updatedLabel = timeNode.InnerText.Trim();

                    string stats = Regex.Replace(statsDiv.InnerText, @"\s+", " ").Trim();
                    var parts = stats.Split('•').Select(p => p.Trim()).ToArray();

                    string downloads = "";
                    if (parts.Length >= 4)
                    {
                        downloads = parts[3].Split(' ')[0];
                    }

                    Console.WriteLine($"SCRAPED: name='{name}', params='{parameters}', updated='{updatedLabel}', downloads='{downloads}'");

                    modelsList.Add(new Model(name, parameters, updatedLabel, downloads));
                }
            }

            return modelsList;
        }
    }
}
