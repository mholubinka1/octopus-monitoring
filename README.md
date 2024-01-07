# Energy Monitoring

This application uses the Octopus API to monitor energy consumption before saving it into an InfluxDB allowing the data to be queried using Flux within Grafana.

### Configuration

Create a new `config.yml` from the supplied `config.yml.template` providing the API Key and Meter Information [given by Octopus on their API page](https://octopus.energy/dashboard/new/accounts/personal-details/api-access)