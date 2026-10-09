from trf3_mod_converter.gui import main

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', help='Reopen saved conversion results')
    main(parser.parse_args().report)
