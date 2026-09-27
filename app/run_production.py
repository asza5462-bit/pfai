from pfai.production_core import ProductionCore, ProductionConfig

if __name__ == '__main__':
    core = ProductionCore(ProductionConfig())
    core.recover()
    core.run_forever()
