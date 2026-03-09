using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace ModelSelector.Backend
{
    public class Model
    {
        string modelName;
        string parameters;
        string lastUpdated;
        string downloads;

        public Model(string modelName, string parameters, string lastUpdated, string downloads)
        {
            this.modelName = modelName;
            this.parameters = parameters;
            this.lastUpdated = lastUpdated;
            this.downloads = downloads;
        }

        public string ModelName 
        {
            get { return modelName; }
        }

        public string Parameters
        {
            get { return parameters; }
        }

        public string LastUpdated
        {
            get { return lastUpdated; }
        }

        public string Downloads
        {
            get { return downloads; }
        }

    }
}
