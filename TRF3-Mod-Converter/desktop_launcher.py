from trf3_mod_converter.gui import main

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', help='Reopen saved conversion results')
    parser.add_argument('--self-check', help='Write an offline packaged-runtime report')
    args = parser.parse_args()
    if args.self_check:
        from trf3_mod_converter.runtime_check import check
        raise SystemExit(check(args.self_check))
    main(args.report)
